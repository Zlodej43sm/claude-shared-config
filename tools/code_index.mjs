#!/usr/bin/env node
// code_index.mjs — symbol index of one repo for the workspace-docs library: every exported function,
// component, class (and its public methods), interface, type, enum, constant and variable, per
// directory, with file:line and how many source files import the file; plus the repo's declared
// dependencies. Writes <=4 KB markdown chunks (YAML frontmatter) so a planner can look for code to
// reuse before adding any.
//
// Usually run through `workspace_docs.py code-index`, which picks the default branch and the out dir:
//   node code_index.mjs --repo <repo dir> --ref <git ref> --out <root>/docs/code-index/<repo>
//        [--name <repo name>] [--typescript <dir holding node_modules/typescript>]
//        [--workspace-packages <json file: {"package name": "repo"}>] [--exclude <regex on path>]
//
// Reads the repo at --ref through `git ls-tree` + `git cat-file` (the default branch, not the
// checkout; nothing is written to the repo). TS/JS is parsed with the TypeScript compiler API
// (resolved from the repo, --typescript, or a sibling repo's node_modules); Kotlin, Java, Swift,
// Python and Go with declaration patterns. Standard library otherwise. Rewrites every .md in --out.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, dirname, join, posix, resolve } from 'node:path';
import { parseArgs } from 'node:util';

const { values: args } = parseArgs({
  options: {
    repo: { type: 'string' },
    ref: { type: 'string' },
    out: { type: 'string' },
    name: { type: 'string' },
    typescript: { type: 'string' },
    'workspace-packages': { type: 'string' },
    exclude: { type: 'string' },
  },
});
if (!args.repo || !args.ref || !args.out) {
  console.error('usage: code_index.mjs --repo <dir> --ref <ref> --out <dir>/docs/code-index/<repo> [--name N] [--typescript DIR] [--workspace-packages JSON] [--exclude REGEX]');
  process.exit(2);
}
const repoDir = resolve(args.repo);
const repoName = args.name ?? basename(repoDir);
const outDir = resolve(args.out);
if (!/\/docs\/code-index\/[^/]+$/.test(outDir)) {
  console.error(`refusing --out ${outDir}: it must be <workspace>/docs/code-index/<repo>`);
  process.exit(2);
}

const MAX_CHUNK = 4096;
const BODY_BUDGET = 3100;
const MAX_LINE = 260;
const TODAY = new Date().toISOString().slice(0, 10);
const SRC_EXT = /\.(tsx?|jsx?|mjs|cjs|mts|cts|kt|kts|java|swift|py|go)$/;
const SKIP_DIRS = new Set(['node_modules', 'dist', 'build', 'out', 'coverage', 'vendor', 'Pods', 'examples', 'example',
  '__tests__', '__mocks__', '__fixtures__', 'fixtures', 'mocks', 'test', 'tests', 'androidTest', 'testFixtures',
  'testDebug', 'testRelease', 'e2e', 'cypress', 'generated', 'storybook-static', 'migrations']);
const SKIP_FILE = /(\.(test|spec|stories|story|e2e|d)\.[a-z]+$|\.min\.js$|\.config\.[cm]?[jt]s$|(^|\/)(Test|.*Tests?)\.(kt|java|swift)$|_test\.go$|(^|\/)test_[^/]+\.py$|\.kts$)/;
const MANIFEST = /(^|\/)(package\.json|build\.gradle(\.kts)?|libs\.versions\.toml|requirements[^/]*\.txt|pyproject\.toml|go\.mod|Package\.swift|Podfile)$/;
const extraSkip = args.exclude ? new RegExp(args.exclude) : null;

const git = (...gitArgs) => {
  const res = spawnSync('git', ['-C', repoDir, ...gitArgs], { maxBuffer: 1 << 30 });
  if (res.status !== 0) throw new Error(`git ${gitArgs.join(' ')}: ${res.stderr}`);
  return res.stdout;
};
const sha = git('rev-parse', '--short=10', args.ref).toString().trim();

// ---------------------------------------------------------------- read the tree at the ref
const keep = (path) => {
  const parts = path.split('/');
  if (parts.slice(0, -1).some((part) => part.startsWith('.') || SKIP_DIRS.has(part))) return false;
  if (extraSkip?.test(path)) return false;
  return (SRC_EXT.test(path) && !SKIP_FILE.test(path)) || (MANIFEST.test(path) && parts.length <= 4);
};
const entries = git('ls-tree', '-r', '-z', '--full-tree', args.ref)
  .toString()
  .split('\0')
  .filter(Boolean)
  .map((line) => {
    const [meta, path] = line.split('\t');
    const [, type, oid] = meta.split(' ');
    return { type, oid, path };
  })
  .filter((entry) => entry.type === 'blob' && keep(entry.path));
const tsconfigEntry = git('ls-tree', '-z', '--full-tree', args.ref, 'tsconfig.json').toString().split('\0').filter(Boolean)[0];

const catBatch = (oids) => {
  if (!oids.length) return [];
  const raw = spawnSync('git', ['-C', repoDir, 'cat-file', '--batch'], { input: `${oids.join('\n')}\n`, maxBuffer: 1 << 30 }).stdout;
  const texts = [];
  let pos = 0;
  while (pos < raw.length) {
    const eol = raw.indexOf(10, pos);
    const size = Number(raw.subarray(pos, eol).toString().split(' ')[2]);
    texts.push(raw.subarray(eol + 1, eol + 1 + size).toString('utf8'));
    pos = eol + 1 + size + 1;
  }
  return texts;
};
const contents = catBatch(entries.map((entry) => entry.oid));
const files = new Map(entries.map((entry, index) => [entry.path, contents[index]]));
const tsconfigText = tsconfigEntry ? catBatch([tsconfigEntry.split('\t')[0].split(' ')[2]])[0] : '';

// ---------------------------------------------------------------- TypeScript compiler
const loadTypescript = () => {
  const candidates = [repoDir, args.typescript, ...readdirSync(dirname(repoDir)).map((dir) => join(dirname(repoDir), dir))].filter(Boolean);
  for (const dir of candidates) {
    if (existsSync(join(dir, 'node_modules/typescript/package.json'))) return createRequire(join(dir, 'package.json'))('typescript');
  }
  return null;
};
const isTsLike = (path) => /\.(tsx?|jsx?|mjs|cjs|mts|cts)$/.test(path);
const ts = [...files.keys()].some(isTsLike) ? loadTypescript() : null;
if ([...files.keys()].some(isTsLike) && !ts) {
  console.error(`no TypeScript compiler found for ${repoName}: run \`npm ci\` in it or a sibling repo, or pass --typescript <dir>`);
  process.exit(3);
}

// ---------------------------------------------------------------- helpers
const clip = (text, max) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
const list = (names, max) => (names.length > max ? `${names.slice(0, max).join(', ')}, +${names.length - max}` : names.join(', '));
const oneLine = (text) => text.replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- TS / JS
const tsAliases = (() => {
  if (!ts || !tsconfigText) return [];
  const { config } = ts.parseConfigFileTextToJson('tsconfig.json', tsconfigText);
  const options = config?.compilerOptions ?? {};
  const baseUrl = posix.normalize(options.baseUrl ?? '.');
  const aliases = Object.entries(options.paths ?? {}).flatMap(([pattern, targets]) =>
    targets.map((target) => ({ prefix: pattern.replace(/\*$/, ''), target: posix.join(baseUrl, target.replace(/\*$/, '')) })),
  );
  return options.baseUrl ? [...aliases, { prefix: '', target: baseUrl }] : aliases;
})();
const TS_EXT = ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '/index.ts', '/index.tsx', '/index.js', '/index.jsx'];
const resolveModule = (fromPath, spec) => {
  const bases = spec.startsWith('.')
    ? [posix.join(posix.dirname(fromPath), spec)]
    : tsAliases.filter((alias) => spec.startsWith(alias.prefix)).map((alias) => posix.join(alias.target, spec.slice(alias.prefix.length)));
  for (const base of bases) {
    const stripped = base.replace(/\.(js|jsx|mjs|cjs)$/, '');
    for (const candidate of [base, stripped].flatMap((b) => TS_EXT.map((ext) => b + ext))) {
      if (files.has(candidate) && isTsLike(candidate)) return candidate;
    }
  }
  return undefined;
};

const hasModifier = (node, kind) => node.modifiers?.some((modifier) => modifier.kind === kind);

function tsFile(path, text) {
  const kind = /\.tsx$/.test(path) ? ts.ScriptKind.TSX : /\.(jsx?|mjs|cjs)$/.test(path) ? ts.ScriptKind.JSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind);
  const lineOf = (node) => source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
  const local = new Map();
  const exported = [];
  const imports = [];
  const addExport = (name, node) => exported.push({ name, node });

  for (const statement of source.statements) {
    if ((ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement)) && statement.moduleSpecifier) {
      imports.push(statement.moduleSpecifier.text);
    }
    const isExport = hasModifier(statement, ts.SyntaxKind.ExportKeyword);
    const isDefault = hasModifier(statement, ts.SyntaxKind.DefaultKeyword);
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name)) continue;
        local.set(declaration.name.text, declaration);
        if (isExport) addExport(declaration.name.text, declaration);
        // CommonJS: const x = require(...) is not a symbol; module.exports handled below
      }
    } else if (
      (ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement) || ts.isInterfaceDeclaration(statement) ||
        ts.isTypeAliasDeclaration(statement) || ts.isEnumDeclaration(statement) || ts.isModuleDeclaration(statement))
    ) {
      const name = statement.name?.text ?? (isDefault ? `default (${basename(path).replace(/\.[^.]+$/, '')})` : undefined);
      if (!name) continue;
      local.set(name, statement);
      if (isExport) addExport(name, statement);
    } else if (ts.isExportDeclaration(statement) && !statement.moduleSpecifier && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
      for (const element of statement.exportClause.elements) {
        const target = local.get((element.propertyName ?? element.name).text);
        if (target) addExport(element.name.text, target);
      }
    } else if (ts.isExportAssignment(statement)) {
      const expression = statement.expression;
      if (ts.isIdentifier(expression) && local.has(expression.text)) addExport(expression.text, local.get(expression.text));
      else addExport(`default (${basename(path).replace(/\.[^.]+$/, '')})`, expression);
    } else if (ts.isExpressionStatement(statement) && ts.isBinaryExpression(statement.expression)) {
      // CommonJS: module.exports = {...} | module.exports = fn | exports.name = ...
      const { left, right } = statement.expression;
      const leftText = left.getText(source);
      if (leftText === 'module.exports') {
        if (ts.isObjectLiteralExpression(right)) {
          for (const property of right.properties) {
            const name = property.name?.getText(source);
            if (!name) continue;
            addExport(name, ts.isShorthandPropertyAssignment(property) ? local.get(name) ?? property : property.initializer ?? property);
          }
        } else if (ts.isIdentifier(right) && local.has(right.text)) addExport(right.text, local.get(right.text));
        else addExport(`module.exports (${basename(path)})`, right);
      } else if (/^(module\.)?exports\.\w+$/.test(leftText)) {
        addExport(leftText.split('.').pop(), right);
      }
    }
  }

  const fieldsOf = (type) => {
    if (!type) return undefined;
    const members = (node) => list(node.members.filter((m) => m.name).map((m) => `${m.name.getText(source)}${m.questionToken ? '?' : ''}`), 8);
    if (ts.isTypeLiteralNode(type)) return members(type);
    if (!ts.isTypeReferenceNode(type) || type.typeArguments) return undefined;
    const declaration = local.get(type.typeName.getText(source));
    if (declaration && ts.isInterfaceDeclaration(declaration)) return members(declaration);
    if (declaration && ts.isTypeAliasDeclaration(declaration) && ts.isTypeLiteralNode(declaration.type)) return members(declaration.type);
    return undefined;
  };
  const param = (p) => {
    if (ts.isObjectBindingPattern(p.name)) return `{${fieldsOf(p.type) ?? list(p.name.elements.map((e) => e.name.getText(source)), 8)}}`;
    const name = p.name.getText(source) + (p.questionToken || p.initializer ? '?' : '');
    const fields = fieldsOf(p.type);
    return fields ? `${name}: {${fields}}` : `${p.dotDotDotToken ? '...' : ''}${name}`;
  };
  const params = (fn) => clip(fn.parameters.map(param).join(', '), 120);
  const unwrap = (node) => {
    let init = node;
    for (;;) {
      if (ts.isAsExpression(init) || ts.isParenthesizedExpression(init) || (ts.SatisfiesExpression && ts.isSatisfiesExpression?.(init))) init = init.expression;
      else if (ts.isCallExpression(init) && init.arguments.length && init.arguments.some((a) => ts.isArrowFunction(a) || ts.isFunctionExpression(a))) {
        init = init.arguments.find((a) => ts.isArrowFunction(a) || ts.isFunctionExpression(a)); // memo(fn), forwardRef(fn), withX(fn)
      } else return init;
    }
  };
  const isComponentName = (name) => /^[A-Z]/.test(name) && /\.(tsx|jsx)$/.test(path);
  const classMembers = (node) =>
    node.members
      .filter((m) => (ts.isMethodDeclaration(m) || ts.isGetAccessor(m)) && m.name && !ts.isPrivateIdentifier(m.name) &&
        !hasModifier(m, ts.SyntaxKind.PrivateKeyword) && !hasModifier(m, ts.SyntaxKind.ProtectedKeyword))
      .map((m) => `.${m.name.getText(source)}`);

  const describe = (name, node) => {
    if (!node) return { kind: 'const', sig: '' };
    if (ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) || ts.isMethodDeclaration(node)) {
      return { kind: isComponentName(name) ? 'cmp' : 'fn', sig: `(${params(node)})` };
    }
    if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
      const members = classMembers(node);
      const heritage = node.heritageClauses?.map((clause) => oneLine(clause.getText(source))).join(' ');
      return { kind: 'class', sig: `${heritage ? ` ${clip(heritage, 50)}` : ''}${members.length ? ` {${list(members, 14)}}` : ''}` };
    }
    if (ts.isInterfaceDeclaration(node)) return { kind: 'ifc', sig: ` {${list(node.members.filter((m) => m.name).map((m) => m.name.getText(source) + (m.questionToken ? '?' : '')), 10)}}` };
    if (ts.isTypeAliasDeclaration(node)) {
      const type = node.type;
      if (ts.isTypeLiteralNode(type)) return { kind: 'type', sig: ` {${list(type.members.filter((m) => m.name).map((m) => m.name.getText(source) + (m.questionToken ? '?' : '')), 10)}}` };
      return { kind: 'type', sig: ` = ${clip(oneLine(type.getText(source)), 70)}` };
    }
    if (ts.isEnumDeclaration(node)) return { kind: 'enum', sig: ` {${list(node.members.map((m) => m.name.getText(source)), 12)}}` };
    if (ts.isModuleDeclaration(node)) return { kind: 'ns', sig: '' };
    if (ts.isVariableDeclaration(node) || ts.isPropertyAssignment?.(node)) {
      const init = node.initializer ? unwrap(node.initializer) : undefined;
      if (!init) return { kind: 'const', sig: node.type ? `: ${clip(oneLine(node.type.getText(source)), 50)}` : '' };
      return describe(name, init);
    }
    if (ts.isObjectLiteralExpression(node)) {
      return { kind: 'obj', sig: ` {${list(node.properties.map((p) => p.name?.getText(source)).filter(Boolean), 12)}}` };
    }
    if (ts.isArrayLiteralExpression(node)) return { kind: 'const', sig: ` [${node.elements.length} items]` };
    if (ts.isCallExpression(node) || ts.isTaggedTemplateExpression(node) || ts.isNewExpression(node)) {
      const callee = ts.isTaggedTemplateExpression(node) ? node.tag : node.expression;
      const calleeText = callee.getText(source).split('(')[0].replace(/\s+/g, '');
      return { kind: 'const', sig: ` = ${ts.isNewExpression(node) ? 'new ' : ''}${clip(calleeText, 40)}(…)` };
    }
    if (ts.isStringLiteral(node) || ts.isNumericLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ||
      node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword) {
      return { kind: 'const', sig: ` = ${clip(oneLine(node.getText(source)), 40)}` };
    }
    return { kind: 'const', sig: '' };
  };

  const seen = new Set();
  const symbols = [];
  for (const { name, node } of exported) {
    if (seen.has(name)) continue;
    seen.add(name);
    const { kind, sig } = describe(name, node);
    symbols.push({ kind, name, sig, line: node ? lineOf(node) : 1 });
  }
  return { symbols, imports };
}

// ---------------------------------------------------------------- Kotlin, Java, Swift, Python, Go
const argNames = (raw) =>
  raw === undefined ? '…' : clip(raw.split(',').map((part) => part.replace(/@\w+(\([^)]*\))?/g, '').trim().replace(/^(vararg|val|var|_)\s+/, '').split(/[:=\s]/)[0]).filter(Boolean).join(', '), 100);
const KT_MODS = /^((public|internal|protected|open|abstract|sealed|data|enum|inline|value|annotation|suspend|override|operator|infix|tailrec|external|const|lateinit|inner|companion|actual|expect|fun)\s+)*$/;
const SWIFT_MODS = /^((public|open|internal|final|static|class|override|mutating|convenience|required|nonisolated|lazy|dynamic|indirect|@\w+(\([^)]*\))?)\s+)*$/;

function patternFile(path, text) {
  const symbols = [];
  let owner = null;
  const lines = text.split('\n');
  const add = (kind, name, sig, line) => {
    const symbol = { kind, name, sig, line, members: [] };
    symbols.push(symbol);
    return symbol;
  };
  const member = (name, line) => owner && owner.members.length < 40 && owner.members.push(`.${name}`);
  lines.forEach((text, index) => {
    const line = index + 1;
    const indent = text.match(/^\s*/)[0].replace(/\t/g, '    ').length;
    if (/\.(kt)$/.test(path)) {
      const m = text.match(/^\s*(.*?)\b(fun|class|interface|object|val|var|typealias)\s+(?:<[^>]+>\s*)?([\w.`]+)(?:\s*\(([^)]*)\)?)?/);
      if (!m || !KT_MODS.test(m[1]) || /\b(private|protected)\b/.test(m[1])) return;
      const [, mods, word, name] = m;
      const params = text.includes('(') && !text.trimEnd().endsWith('(') && m[4] !== undefined ? m[4] : undefined;
      if (indent === 0) {
        const kind = word === 'fun' ? 'fun' : word === 'class' ? (/\benum\b/.test(mods) ? 'enum' : /\bdata\b/.test(mods) ? 'data' : 'class') : word === 'interface' ? 'ifc' : word === 'object' ? 'obj' : word === 'typealias' ? 'type' : 'val';
        const symbol = add(kind, name, word === 'fun' ? `(${argNames(params)})` : '', line);
        owner = ['class', 'data', 'enum', 'ifc', 'obj'].includes(kind) ? symbol : null;
      } else if (indent === 4 && word === 'fun') member(name, line);
    } else if (/\.java$/.test(path)) {
      const type = text.match(/^(\s*)public\s+(?:(?:static|final|abstract|sealed)\s+)*(class|interface|enum|record|@interface)\s+(\w+)/);
      if (type && type[1].length === 0) owner = add(type[2] === 'interface' ? 'ifc' : type[2] === 'enum' ? 'enum' : 'class', type[3], '', line);
      const method = text.match(/^\s{4}public\s+(?:(?:static|final|synchronized|abstract|default)\s+)*(?:<[^>]+>\s+)?[\w<>[\],.? ]+\s+(\w+)\s*\(/);
      if (method) member(method[1], line);
    } else if (/\.swift$/.test(path)) {
      const m = text.match(/^\s*(.*?)\b(func|class|struct|enum|protocol|extension|typealias|actor|let|var)\s+([\w.]+)(?:\s*(?:<[^>]+>)?\s*\(([^)]*)\)?)?/);
      if (!m || !SWIFT_MODS.test(m[1]) || /\b(private|fileprivate)\b/.test(m[1])) return;
      const [, , word, name] = m;
      if (indent === 0) {
        const kind = { func: 'func', class: 'class', struct: 'struct', enum: 'enum', protocol: 'proto', extension: 'ext', typealias: 'type', actor: 'actor', let: 'let', var: 'var' }[word];
        const symbol = add(kind, name, word === 'func' ? `(${argNames(text.trimEnd().endsWith('(') ? undefined : m[4])})` : '', line);
        owner = ['class', 'struct', 'enum', 'proto', 'ext', 'actor'].includes(kind) ? symbol : null;
      } else if (indent === 4 && word === 'func') member(name, line);
    } else if (/\.py$/.test(path)) {
      const m = text.match(/^(\s*)(?:async\s+)?(def|class)\s+(\w+)\s*(?:\(([^)]*)\)?)?/);
      if (m && !m[3].startsWith('_')) {
        if (m[1].length === 0) {
          const symbol = add(m[2] === 'def' ? 'def' : 'class', m[3], m[2] === 'def' ? `(${argNames(m[4])})` : '', line);
          owner = m[2] === 'class' ? symbol : null;
        } else if (m[1].length === 4 && m[2] === 'def') member(m[3], line);
      } else {
        const constant = text.match(/^([A-Z][A-Z0-9_]{2,})\s*(?::[^=]+)?=/);
        if (constant) add('const', constant[1], '', line);
      }
    } else if (/\.go$/.test(path)) {
      const fn = text.match(/^func\s+(?:\((\w+\s+)?\*?(\w+)\)\s*)?([A-Z]\w*)\s*\(([^)]*)\)?/);
      if (fn) {
        const receiver = fn[2] && symbols.find((symbol) => symbol.name === fn[2]);
        if (receiver) receiver.members.push(`.${fn[3]}`);
        else add('func', fn[2] ? `${fn[2]}.${fn[3]}` : fn[3], `(${argNames(fn[4])})`, line);
      }
      const type = text.match(/^type\s+([A-Z]\w*)\s+(struct|interface|\w+)/);
      if (type) add(type[2] === 'interface' ? 'ifc' : type[2] === 'struct' ? 'struct' : 'type', type[1], '', line);
    }
  });
  for (const symbol of symbols) if (symbol.members.length) symbol.sig += ` {${list(symbol.members, 14)}}`;
  return { symbols, imports: [] };
}

// ---------------------------------------------------------------- parse every file
const parsed = new Map();
for (const [path, text] of files) {
  if (MANIFEST.test(path) && !SRC_EXT.test(path)) continue;
  try {
    parsed.set(path, isTsLike(path) ? tsFile(path, text) : patternFile(path, text));
  } catch (error) {
    console.error(`skipped ${path}: ${error.message}`);
  }
}
const importers = new Map();
for (const [path, { imports }] of parsed) {
  for (const target of new Set(imports.map((spec) => resolveModule(path, spec)).filter(Boolean))) {
    if (target !== path) importers.set(target, (importers.get(target) ?? 0) + 1);
  }
}

// ---------------------------------------------------------------- dependencies
const workspacePackages = args['workspace-packages'] ? JSON.parse(readFileSync(args['workspace-packages'], 'utf8')) : {};
const depLines = [];
for (const [path, text] of [...files].filter(([path]) => MANIFEST.test(path)).sort(([a], [b]) => a.localeCompare(b))) {
  const deps = [];
  const workspace = (name) => (workspacePackages[name] && workspacePackages[name] !== repoName ? ` (workspace: \`docs/code-index/${workspacePackages[name]}/README.md\`)` : '');
  if (path.endsWith('package.json')) {
    let json;
    try { json = JSON.parse(text); } catch { continue; }
    for (const field of ['dependencies', 'peerDependencies', 'devDependencies']) {
      const names = Object.entries(json[field] ?? {}).map(([name, version]) => `${name}@${version}${workspace(name)}`);
      if (names.length) deps.push(`- ${field}: ${names.join(', ')}`);
    }
    if (json.name) deps.unshift(`- package: \`${json.name}\`${json.version ? `@${json.version}` : ''}`);
  } else if (path.endsWith('libs.versions.toml')) {
    const section = text.split(/^\[libraries\]/m)[1]?.split(/^\[/m)[0] ?? '';
    const names = [...section.matchAll(/^\s*([\w.-]+)\s*=\s*\{?\s*(?:module\s*=\s*"([^"]+)"|group\s*=\s*"([^"]+)",\s*name\s*=\s*"([^"]+)")?/gm)]
      .map((m) => `${m[1]}${m[2] ? ` (${m[2]})` : m[3] ? ` (${m[3]}:${m[4]})` : ''}`);
    if (names.length) deps.push(`- libraries: ${names.join(', ')}`);
  } else if (/build\.gradle/.test(path)) {
    const names = [...text.matchAll(/^\s*(implementation|api|kapt|ksp)\s*\(?\s*([^)\n]+)\)?/gm)].map((m) => oneLine(m[2]).replace(/["']/g, ''));
    if (names.length) deps.push(`- ${[...new Set(names)].join(', ')}`);
  } else {
    const names = text.split('\n').map((line) => line.trim()).filter((line) => line && !/^[#[]|^\/\//.test(line));
    if (names.length) deps.push(`- ${clip(names.join(', '), 1500)}`);
  }
  if (deps.length) depLines.push(`\n**${path}**\n`, ...deps.map((dep) => `${clip(dep, 1800)}\n`));
}

// ---------------------------------------------------------------- chunks
const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'root';
const written = [];
const write = (fileName, frontmatter, body) => {
  const head = Object.entries(frontmatter).map(([key, value]) => `${key}: ${Array.isArray(value) ? `[${value.join(', ')}]` : value}`).join('\n');
  const text = `---\n${head}\n---\n${body}`;
  if (Buffer.byteLength(text) > MAX_CHUNK) throw new Error(`${fileName} is ${Buffer.byteLength(text)} bytes`);
  writeFileSync(join(outDir, fileName), text);
  written.push(fileName);
};
const paginate = (lines, budget) => {
  const pages = [];
  let current = [];
  let size = 0;
  let header = '';
  for (const line of lines) {
    if (line.startsWith('\n**') || line.startsWith('\n### ')) header = line;
    if (size + Buffer.byteLength(line) > budget && current.length) {
      pages.push(current);
      current = line === header ? [] : [header.replace(/\*\*\n$/, ' (cont.)**\n').replace(/\/\n$/, '/ (cont.)\n')];
      size = Buffer.byteLength(current.join(''));
    }
    current.push(line);
    size += Buffer.byteLength(line);
  }
  if (current.length) pages.push(current);
  return pages;
};

mkdirSync(outDir, { recursive: true });
for (const file of readdirSync(outDir)) if (file.endsWith('.md')) rmSync(join(outDir, file));

// JVM source roots repeat the package path in every directory (app/src/main/kotlin/com/acme/app/…):
// shorten <module>/src/<set>/<lang>/<common package prefix>/ to <module>/…/ and say so in the README.
const JVM_ROOT = /^(.*?\/?)src\/[A-Za-z]+\/(kotlin|java)\//;
const packagePrefix = (() => {
  const counts = new Map();
  let total = 0;
  for (const path of parsed.keys()) {
    if (!JVM_ROOT.test(path)) continue;
    total += 1;
    const key = path.replace(JVM_ROOT, '').split('/').slice(0, 3).join('/');
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const [top, count] = [...counts].sort((a, b) => b[1] - a[1])[0] ?? [];
  return top && count * 2 >= total && top.split('/').length === 3 ? top.split('/') : [];
})();
const elided = packagePrefix.length ? `src/<set>/<kotlin|java>/${packagePrefix.join('/')}/` : '';
const showDir = (dir) => {
  const match = dir.match(JVM_ROOT);
  if (!match) return dir;
  let rest = dir.replace(JVM_ROOT, '').split('/');
  if (packagePrefix.length && packagePrefix.every((segment, i) => rest[i] === segment)) rest = rest.slice(packagePrefix.length);
  const moduleSegments = match[1].split('/').filter(Boolean);
  if (moduleSegments.length && moduleSegments.every((segment, i) => rest[i] === segment)) rest = rest.slice(moduleSegments.length);
  return `${match[1]}…/${rest.join('/')}`;
};

const byDir = new Map();
const kinds = new Map();
for (const [path, { symbols }] of [...parsed].sort(([a], [b]) => a.localeCompare(b))) {
  if (!symbols.length) continue;
  const dir = posix.dirname(path) === '.' ? '(root)' : showDir(`${posix.dirname(path)}/`);
  const used = importers.get(path);
  const lines = symbols.map((symbol) => {
    kinds.set(symbol.kind, (kinds.get(symbol.kind) ?? 0) + 1);
    return `${clip(`- ${symbol.kind} \`${symbol.name}\`${symbol.sig} ${basename(path)}:${symbol.line}${used ? ` ←${used}` : ''}`, MAX_LINE)}\n`;
  });
  byDir.set(dir, [...(byDir.get(dir) ?? []), ...lines]);
}
const symbolCount = [...kinds.values()].reduce((a, b) => a + b, 0);

const chunkRows = [];
const usedNames = new Set(['README', 'dependencies']);
const pages = paginate([...byDir].flatMap(([dir, lines]) => [`\n### ${dir}\n`, ...lines]), BODY_BUDGET);
for (const page of pages) {
  const dirs = page.filter((line) => line.startsWith('\n### ')).map((line) => line.slice(5, -1).replace(/ \(cont\.\)$/, ''));
  let name = slug(dirs[0] ?? 'root');
  for (let n = 2; usedNames.has(name); n += 1) name = `${slug(dirs[0] ?? 'root')}-${n}`;
  usedNames.add(name);
  const segments = [...new Set(dirs.flatMap((dir) => dir.split('/')).filter((s) => s && !s.startsWith('(')))].slice(0, 8);
  const range = dirs.length > 1 ? `${dirs[0]} … ${dirs.at(-1)}` : dirs[0] ?? '(root)';
  write(
    `${name}.md`,
    {
      summary: `${repoName} code index — ${clip(range, 110)}: exported symbols with file:line and importer counts`,
      keywords: ['code index', repoName, ...segments],
      verified: TODAY,
    },
    `# Code index: ${repoName} — ${clip(range, 90)}\n\nIndex: \`docs/code-index/${repoName}/README.md\`. Generated from \`${args.ref}\` @ \`${sha}\`; do not edit.\n${page.join('')}`,
  );
  chunkRows.push(`| \`${name}.md\` | ${clip(range.replace(/\|/g, '\\|'), 110)} |\n`);
}

const depPages = paginate(depLines, BODY_BUDGET);
depPages.forEach((page, index) => {
  const name = index ? `dependencies-${index + 1}` : 'dependencies';
  write(
    `${name}.md`,
    {
      summary: `${repoName} declared dependencies${depPages.length > 1 ? ` part ${index + 1}/${depPages.length}` : ''} — libraries already available before adding a new one`,
      keywords: ['dependencies', 'packages', 'libraries', 'versions', repoName],
      verified: TODAY,
    },
    `# Dependencies: ${repoName}${depPages.length > 1 ? ` (${index + 1}/${depPages.length})` : ''}\n\nIndex: \`docs/code-index/${repoName}/README.md\`. From \`${args.ref}\` @ \`${sha}\`; do not edit.\n${page.join('')}`,
  );
});

const kindList = [...kinds].sort((a, b) => b[1] - a[1]).map(([kind, count]) => `${kind} ${count}`).join(', ');
const intro = `# Code index: ${repoName}

Index of all: \`docs/code-index/README.md\`. Generated from \`${args.ref}\` @ \`${sha}\` on ${TODAY} by the shared \`code_index.mjs\`; do not edit, regenerate (\`workspace_docs.py code-index --repos ${repoName}\`).

- **Symbols:** ${symbolCount} in ${parsed.size} source files (${kindList || 'none'}). Tests, stories, mocks, fixtures, generated and build output are left out.
- **Dependencies:** ${depPages.length ? `\`docs/code-index/${repoName}/dependencies.md\`` : 'no manifest found'}.
- **Search:** \`workspace_docs.py symbol <name> --repo ${repoName}\`, or grep \`docs/code-index/${repoName}/\`.
${elided ? `- **Paths:** \`<module>/…/\` stands for \`<module>/${elided}\` plus the module path when the package repeats it.\n` : ''}- **Line format:** \`- <kind> \`name\`(params) {fields | .methods} file:line ←N\`; ←N = source files importing that file (relative imports and tsconfig paths only; 0 shown as nothing).
`;
const indexPages = paginate(chunkRows, BODY_BUDGET - Buffer.byteLength(intro) - 250);
const tableHead = '\n| Chunk | Directories |\n|---|---|\n';
indexPages.forEach((page, index) => {
  const name = index ? `README-${index + 1}` : 'README';
  const more = indexPages.length > 1 && index === 0
    ? `\n**More:** chunk lists \`docs/code-index/${repoName}/README-2.md\`${indexPages.length > 2 ? ` to \`README-${indexPages.length}.md\`` : ''}.\n`
    : '';
  const frontmatter = {
    summary: `${repoName} code index${index ? ` (chunk list ${index + 1}/${indexPages.length})` : ''} — every exported function, component, class, type, enum and constant by directory, to reuse before adding code`,
    keywords: ['code index', 'symbols', 'reuse', 'existing function', 'duplicate', 'before implementation', repoName],
    verified: TODAY,
  };
  if (!index) Object.assign(frontmatter, { ref: args.ref, commit: sha, symbols: symbolCount, files: parsed.size, chunks: pages.length });
  const top = index ? `# Code index: ${repoName} (chunk list ${index + 1}/${indexPages.length})\n\nIndex: \`docs/code-index/${repoName}/README.md\`.\n` : `${intro}${more}`;
  write(`${name}.md`, frontmatter, `${top}${tableHead}${page.join('')}`);
});
if (!indexPages.length) {
  write('README.md', {
    summary: `${repoName} code index — no source files in a supported language`,
    keywords: ['code index', repoName], verified: TODAY, ref: args.ref, commit: sha, symbols: 0, files: 0, chunks: 0,
  }, `${intro}\nNo source files in a supported language (TS/JS, Kotlin, Java, Swift, Python, Go).\n`);
}

console.log(JSON.stringify({ repo: repoName, ref: args.ref, commit: sha, symbols: symbolCount, files: parsed.size, chunks: written.length }));
