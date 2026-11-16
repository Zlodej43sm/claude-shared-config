() => {
  const MAX_NODES = 1500;
  const MAX_DEPTH = 40;
  const MAX_TEXT = 300;
  const MAX_SVG = 6000;
  const MIN_BLOCK_HEIGHT = 24;

  const LAYOUT_PROPS = [
    'display', 'position', 'top', 'right', 'bottom', 'left', 'zIndex',
    'flexDirection', 'flexWrap', 'justifyContent', 'alignItems', 'alignSelf', 'alignContent',
    'flexGrow', 'flexShrink', 'flexBasis', 'order', 'rowGap', 'columnGap',
    'gridTemplateColumns', 'gridTemplateRows', 'gridColumn', 'gridRow', 'gridAutoFlow',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'marginTop', 'marginRight', 'marginBottom', 'marginLeft',
    'minWidth', 'maxWidth', 'minHeight', 'maxHeight', 'boxSizing', 'overflowX', 'overflowY',
    'aspectRatio', 'objectFit', 'objectPosition', 'transform',
  ];
  const PAINT_PROPS = [
    'backgroundColor', 'backgroundImage', 'backgroundSize', 'backgroundPosition', 'backgroundRepeat',
    'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'borderTopStyle', 'borderRightStyle', 'borderBottomStyle', 'borderLeftStyle',
    'borderTopColor', 'borderRightColor', 'borderBottomColor', 'borderLeftColor',
    'borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius',
    'boxShadow', 'outlineStyle', 'outlineWidth', 'outlineColor', 'opacity', 'filter', 'backdropFilter',
    'mixBlendMode', 'cursor', 'transition',
  ];
  const TEXT_PROPS = [
    'color', 'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'lineHeight', 'letterSpacing',
    'textAlign', 'textTransform', 'textDecorationLine', 'textDecorationColor', 'whiteSpace',
    'textOverflow', 'wordBreak', 'fontFeatureSettings', 'fontVariantNumeric', 'webkitLineClamp',
  ];
  const DEFAULT_VALUES = new Set([
    '', 'none', 'normal', 'auto', '0px', '0', 'static', 'visible', 'rgba(0, 0, 0, 0)', 'start',
    'nowrap', 'row', 'stretch', 'content-box', 'repeat', '0% 0%', 'auto auto', 'baseline', 'medium',
    '1', 'ease 0s', 'all 0s ease 0s', 'currentcolor', 'solid', 'manual', 'separate',
  ]);
  const DEFAULT_BY_PROP = {
    flexShrink: '1', flexGrow: '0', order: '0', opacity: '1', fontStyle: 'normal',
    borderTopStyle: 'none', borderRightStyle: 'none', borderBottomStyle: 'none', borderLeftStyle: 'none',
    whiteSpace: 'normal', textAlign: 'start', webkitLineClamp: 'none', objectFit: 'fill', objectPosition: '50% 50%',
    transition: 'all', cursor: 'auto',
  };
  const SIDES = ['Top', 'Right', 'Bottom', 'Left'];
  const relevant = (prop, style, tag) => {
    const side = SIDES.find((name) => prop.startsWith(`border${name}`) && !prop.endsWith('Radius'));
    if (side) return parseFloat(style[`border${side}Width`]) > 0 && style[`border${side}Style`] !== 'none';
    if (prop.startsWith('outline')) return style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
    if (prop === 'textDecorationColor') return style.textDecorationLine !== 'none';
    if (prop === 'objectFit' || prop === 'objectPosition') return ['img', 'video', 'picture', 'canvas'].includes(tag);
    if (['top', 'right', 'bottom', 'left', 'zIndex'].includes(prop)) return style.position !== 'static';
    if (prop === 'textOverflow') return style.overflowX !== 'visible';
    return true;
  };
  const ATTRS = ['href', 'src', 'alt', 'title', 'aria-label', 'role', 'type', 'placeholder', 'name', 'for', 'target'];
  const LANDMARK_BY_ROLE = { banner: 'header', contentinfo: 'footer', navigation: 'nav', main: 'main', complementary: 'aside' };

  const round = (value) => Math.round(value * 100) / 100;

  const isVisible = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const cssPath = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        return parts.join(' > ');
      }
      let part = node.localName;
      const parent = node.parentElement;
      if (parent) {
        const sameTag = [...parent.children].filter((child) => child.localName === node.localName);
        if (sameTag.length > 1) part += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(' > ');
  };

  const pageBox = (el) => {
    const rect = el.getBoundingClientRect();
    return { x: round(rect.left + scrollX), y: round(rect.top + scrollY), w: round(rect.width), h: round(rect.height) };
  };

  const landmarkOf = (el) => {
    const role = el.getAttribute('role');
    if (role && LANDMARK_BY_ROLE[role]) return LANDMARK_BY_ROLE[role];
    return ['header', 'footer', 'nav', 'main', 'aside', 'section', 'article', 'form'].includes(el.localName) ? el.localName : null;
  };

  const headingOf = (el) => {
    const heading = el.querySelector('h1, h2, h3, [role=heading]');
    const text = (heading ? heading.textContent : el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    return text.slice(0, 80) || null;
  };

  const visibleChildren = (el) => [...el.children].filter((child) => isVisible(child));

  const unwrapContainer = (root) => {
    let container = root;
    for (;;) {
      const children = visibleChildren(container).filter((child) => child.getBoundingClientRect().height >= MIN_BLOCK_HEIGHT);
      const containerHeight = container.getBoundingClientRect().height || document.documentElement.scrollHeight;
      if (children.length !== 1 || children[0].getBoundingClientRect().height < 0.9 * containerHeight) return container;
      if (landmarkOf(children[0]) === 'main') return children[0].parentElement;
      container = children[0];
    }
  };

  const describeBlock = (el) => ({
    selector: cssPath(el),
    tag: el.localName,
    landmark: landmarkOf(el),
    id: el.id || null,
    classes: [...el.classList].slice(0, 4),
    position: getComputedStyle(el).position,
    box: pageBox(el),
    heading: headingOf(el),
  });

  const blocks = () => {
    const container = unwrapContainer(document.body);
    const top = visibleChildren(container).filter((child) => child.getBoundingClientRect().height >= MIN_BLOCK_HEIGHT
      || ['fixed', 'sticky'].includes(getComputedStyle(child).position));
    const expanded = top.flatMap((child) => {
      if (landmarkOf(child) !== 'main') return [child];
      const inner = unwrapContainer(child);
      const sections = visibleChildren(inner).filter((section) => section.getBoundingClientRect().height >= MIN_BLOCK_HEIGHT);
      return sections.length > 1 ? sections : [child];
    });
    return {
      url: location.href,
      viewport: { w: innerWidth, h: innerHeight },
      document: { w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight },
      blocks: expanded.map(describeBlock),
    };
  };

  const resolveBlock = (query) => {
    const byLandmark = {
      header: 'header, [role=banner]', footer: 'footer, [role=contentinfo]',
      nav: 'nav, [role=navigation]', main: 'main, [role=main]',
    }[String(query).toLowerCase()];
    const candidates = [];
    if (byLandmark) candidates.push(...document.querySelectorAll(byLandmark));
    if (!candidates.length) {
      try { candidates.push(...document.querySelectorAll(query)); } catch (error) { /* not a selector: match by heading text below */ }
    }
    if (!candidates.length) {
      const needle = String(query).toLowerCase();
      const heading = [...document.querySelectorAll('h1, h2, h3, [role=heading]')]
        .find((node) => isVisible(node) && node.textContent.toLowerCase().includes(needle));
      if (heading) candidates.push(heading.closest('section, article, header, footer, aside, [role=region]') || heading.parentElement);
    }
    const visible = candidates.filter(isVisible);
    if (!visible.length) return null;
    return visible.sort((a, b) => b.getBoundingClientRect().height * b.getBoundingClientRect().width
      - a.getBoundingClientRect().height * a.getBoundingClientRect().width)[0];
  };

  const ownText = (el) => [...el.childNodes]
    .filter((node) => node.nodeType === 3)
    .map((node) => node.textContent).join(' ').replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT);

  const pickStyles = (style, props, parentStyle, tag) => {
    const picked = {};
    for (const prop of props) {
      const value = style[prop];
      if (value === undefined || value === null || !relevant(prop, style, tag)) continue;
      const fallback = DEFAULT_BY_PROP[prop];
      if (fallback !== undefined ? value === fallback : DEFAULT_VALUES.has(value)) continue;
      if (parentStyle && parentStyle[prop] === value) continue;
      picked[prop] = value;
    }
    return picked;
  };

  const collapseSides = (styles, names, shorthand) => {
    const values = names.map((name) => styles[name]);
    if (values.some((value) => value === undefined) || new Set(values).size !== 1) return;
    for (const name of names) delete styles[name];
    styles[shorthand] = values[0];
  };

  const compact = (styles) => {
    collapseSides(styles, ['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius'], 'borderRadius');
    collapseSides(styles, ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'], 'padding');
    collapseSides(styles, ['marginTop', 'marginRight', 'marginBottom', 'marginLeft'], 'margin');
    collapseSides(styles, ['rowGap', 'columnGap'], 'gap');
    const borders = SIDES.map((side) => [styles[`border${side}Width`], styles[`border${side}Style`], styles[`border${side}Color`]].join(' '));
    if (borders.every((border) => border === borders[0]) && styles.borderTopWidth) {
      for (const side of SIDES) {
        delete styles[`border${side}Width`]; delete styles[`border${side}Style`]; delete styles[`border${side}Color`];
      }
      styles.border = borders[0];
    }
    return styles;
  };

  const hasOwnPaint = (style) => style.backgroundColor !== 'rgba(0, 0, 0, 0)' || style.backgroundImage !== 'none'
    || style.boxShadow !== 'none' || ['Top', 'Right', 'Bottom', 'Left'].some((side) => parseFloat(style[`border${side}Width`]) > 0
      && style[`border${side}Style`] !== 'none')
    || ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].some((prop) => parseFloat(style[prop]) > 0)
    || parseFloat(style.borderTopLeftRadius) > 0 || style.display.includes('flex') || style.display.includes('grid')
    || style.position !== 'static' || style.overflowX !== 'visible' || style.transform !== 'none';

  const pseudoNode = (el, which, origin) => {
    const style = getComputedStyle(el, which);
    if (!style.content || style.content === 'none' || style.content === 'normal') return null;
    return {
      tag: which,
      content: style.content.slice(0, MAX_TEXT),
      style: compact({ ...pickStyles(style, LAYOUT_PROPS, null, which), ...pickStyles(style, PAINT_PROPS, null, which),
        ...pickStyles(style, TEXT_PROPS, null, which),
        ...(style.width !== 'auto' ? { width: style.width } : {}), ...(style.height !== 'auto' ? { height: style.height } : {}) }),
      origin,
    };
  };

  const extract = (query, options = {}) => {
    const root = typeof query === 'string' ? resolveBlock(query) : query;
    if (!root) return { error: `no visible element matches ${JSON.stringify(query)}` };
    const rootRect = root.getBoundingClientRect();
    const maxNodes = options.maxNodes || MAX_NODES;
    let count = 0;
    let truncated = false;
    const assets = [];

    const relativeBox = (el) => {
      const rect = el.getBoundingClientRect();
      return [round(rect.left - rootRect.left), round(rect.top - rootRect.top), round(rect.width), round(rect.height)];
    };

    const walk = (el, depth, parentStyle) => {
      if (count >= maxNodes || depth > MAX_DEPTH) { truncated = true; return null; }
      if (!isVisible(el)) return null;
      const style = getComputedStyle(el);
      const text = ownText(el);
      const elementChildren = visibleChildren(el);
      const textStyles = el.textContent.trim() ? pickStyles(style, TEXT_PROPS, parentStyle, el.localName) : {};
      if (!options.keepWrappers && depth > 0 && !text && elementChildren.length === 1 && !hasOwnPaint(style)
        && !['a', 'button', 'svg', 'img', 'picture', 'video', 'input', 'select', 'textarea', 'label', 'ul', 'ol', 'li', 'table'].includes(el.localName)
        && !el.getAttribute('role') && !Object.keys(textStyles).length) {
        return walk(elementChildren[0], depth + 1, parentStyle);
      }
      count += 1;
      const node = { tag: el.localName, box: relativeBox(el) };
      if (depth === 0) node.selector = cssPath(el);
      const attrs = {};
      for (const name of ATTRS) {
        const value = el.getAttribute(name);
        if (value) attrs[name] = value.slice(0, MAX_TEXT);
      }
      if (el.localName === 'img') {
        attrs.src = el.currentSrc || el.src;
        node.natural = [el.naturalWidth, el.naturalHeight];
        assets.push({ kind: 'img', url: attrs.src, alt: el.alt, box: node.box });
      }
      if (Object.keys(attrs).length) node.attrs = attrs;
      if (text) node.text = text;
      const styles = compact({ ...pickStyles(style, LAYOUT_PROPS, null, el.localName), ...pickStyles(style, PAINT_PROPS, null, el.localName), ...textStyles });
      if (Object.keys(styles).length) node.style = styles;
      const bgUrls = style.backgroundImage.match(/url\(["']?([^"')]+)["']?\)/g);
      if (bgUrls) {
        for (const match of bgUrls) assets.push({ kind: 'background', url: match.replace(/^url\(["']?|["']?\)$/g, ''), box: node.box });
      }
      if (el.localName === 'svg') {
        node.svg = el.outerHTML.slice(0, MAX_SVG);
        if (el.outerHTML.length > MAX_SVG) node.svgTruncated = true;
        assets.push({ kind: 'svg', box: node.box, label: el.getAttribute('aria-label') || null });
        return node;
      }
      const children = [];
      for (const which of ['::before', '::after']) {
        const pseudo = pseudoNode(el, which, node.box);
        if (pseudo) children.push(pseudo);
      }
      for (const child of elementChildren) {
        const childNode = walk(child, depth + 1, style);
        if (childNode) children.push(childNode);
      }
      if (children.length) node.children = children;
      return node;
    };

    const tree = walk(root, 0, null);
    return {
      url: location.href,
      viewport: { w: innerWidth, h: innerHeight },
      block: { selector: cssPath(root), box: pageBox(root) },
      nodeCount: count,
      truncated,
      assets,
      tree,
    };
  };

  const readableRules = () => {
    const rules = [];
    for (const sheet of document.styleSheets) {
      try { rules.push(...sheet.cssRules); } catch (error) { /* cross-origin stylesheet: not readable */ }
    }
    return rules;
  };

  const top = (counter, limit) => [...counter.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit)
    .map(([value, uses]) => ({ value, uses }));

  const tokens = () => {
    const customProperties = {};
    const fontFaces = [];
    const mediaQueries = new Set();
    const collect = (rules) => {
      for (const rule of rules) {
        if (rule.type === CSSRule.STYLE_RULE && /(^|,)\s*(:root|html|body)\s*($|,)/.test(rule.selectorText)) {
          for (const name of rule.style) {
            if (name.startsWith('--')) customProperties[name] = rule.style.getPropertyValue(name).trim();
          }
        } else if (rule.type === CSSRule.FONT_FACE_RULE) {
          fontFaces.push({ family: rule.style.getPropertyValue('font-family'), weight: rule.style.getPropertyValue('font-weight'),
            style: rule.style.getPropertyValue('font-style'), src: rule.style.getPropertyValue('src').slice(0, 400) });
        } else if (rule.type === CSSRule.MEDIA_RULE) {
          mediaQueries.add(rule.conditionText || rule.media.mediaText);
          collect(rule.cssRules);
        } else if (rule.cssRules) {
          collect(rule.cssRules);
        }
      }
    };
    collect(readableRules());
    const counters = { color: new Map(), backgroundColor: new Map(), font: new Map(), borderRadius: new Map(), boxShadow: new Map(), gap: new Map() };
    const bump = (map, key) => { if (key && !DEFAULT_VALUES.has(key)) map.set(key, (map.get(key) || 0) + 1); };
    let scanned = 0;
    for (const el of document.body.querySelectorAll('*')) {
      if (scanned >= 5000) break;
      if (!isVisible(el)) continue;
      scanned += 1;
      const style = getComputedStyle(el);
      if (ownText(el)) {
        bump(counters.color, style.color);
        bump(counters.font, `${style.fontFamily.split(',')[0].replace(/["']/g, '').trim()} ${style.fontWeight} ${style.fontSize}/${style.lineHeight} ls:${style.letterSpacing}`);
      }
      bump(counters.backgroundColor, style.backgroundColor);
      bump(counters.borderRadius, style.borderTopLeftRadius);
      bump(counters.boxShadow, style.boxShadow);
      if (style.display.includes('flex') || style.display.includes('grid')) bump(counters.gap, style.columnGap);
    }
    return {
      url: location.href,
      customProperties,
      fontFaces: fontFaces.slice(0, 40),
      loadedFonts: [...document.fonts].filter((face) => face.status === 'loaded')
        .map((face) => `${face.family.replace(/["']/g, '')} ${face.weight} ${face.style}`),
      mediaQueries: [...mediaQueries].slice(0, 40),
      rootFontSize: getComputedStyle(document.documentElement).fontSize,
      mostUsed: Object.fromEntries(Object.entries(counters).map(([name, counter]) => [name, top(counter, 15)])),
    };
  };

  const settle = async () => {
    const step = Math.max(200, Math.floor(innerHeight * 0.8));
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      scrollTo(0, y);
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
    scrollTo(0, 0);
    await document.fonts.ready;
    const pending = [...document.images].filter((img) => !img.complete);
    await Promise.race([
      Promise.all(pending.map((img) => new Promise((resolve) => { img.onload = img.onerror = resolve; }))),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
    return { height: document.documentElement.scrollHeight, imagesStillLoading: [...document.images].filter((img) => !img.complete).length };
  };

  window.__designSpec = { blocks, extract, tokens, settle };
  return 'design-spec helpers installed: blocks(), extract(query), tokens(), settle()';
}
