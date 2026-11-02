// Justice's numerical engine has no DOM adapter. Keep source text and geometry here.
(() => {
  'use strict';

  function create(root, {scrollRoot, onLayout = () => {}}) {
    let source = null, segments = null, fontKey = null, width = -1;
    let records = [], frame = 0, fontsChanged = false, destroyed = false;

    // Every rendered text node is an unchanged source slice. Visual line breaks
    // are block boundaries, while original spaces/newlines remain text nodes.
    function text(parent, start, end) {
      const node = document.createTextNode(source.slice(start, end));
      parent.append(node);
      records.push({node, start, end});
      return node;
    }

    function sourceOffset(node, offset) {
      if (!node || (node !== root && !root.contains(node))) return null;
      const range = document.createRange();
      range.selectNodeContents(root);
      range.setEnd(node, offset);
      return range.toString().length;
    }

    function point(offset, end = false) {
      // At a visual break, use the next line for a start and the prior line
      // for an end. This also retains original spaces between the lines.
      const record = records.find(r => end
        ? r.start < offset && offset <= r.end
        : r.start <= offset && offset < r.end) || records.at(-1);
      return record ? [record.node, Math.max(0, Math.min(offset - record.start, record.node.length))] : [root, 0];
    }

    function rememberSelection() {
      const selection = window.getSelection();
      if (!selection?.rangeCount) return null;
      const anchor = sourceOffset(selection.anchorNode, selection.anchorOffset);
      const focus = sourceOffset(selection.focusNode, selection.focusOffset);
      if (anchor === null && focus === null) return null;
      return {
        collapsed:selection.isCollapsed,
        anchor:anchor === null ? [selection.anchorNode, selection.anchorOffset] : anchor,
        focus:focus === null ? [selection.focusNode, selection.focusOffset] : focus,
      };
    }

    function restoreSelection(saved) {
      if (!saved) return;
      const anchor = typeof saved.anchor === 'number' ? point(saved.anchor) : saved.anchor;
      const focus = saved.collapsed ? anchor : typeof saved.focus === 'number' ? point(saved.focus, true) : saved.focus;
      window.getSelection()?.setBaseAndExtent(...anchor, ...focus);
    }

    function characterRect(node, offset) {
      const range = document.createRange();
      range.setStart(node, offset);
      range.setEnd(node, Math.min(offset + 1, node.length));
      return range.getBoundingClientRect();
    }

    function rememberPosition() {
      const bounds = scrollRoot.getBoundingClientRect();
      for (const record of records) {
        if (!record.node.length) continue;
        const range = document.createRange();
        range.selectNodeContents(record.node);
        const rects = [...range.getClientRects()];
        if (!rects.some(r => r.width && r.bottom > bounds.top && r.top < bounds.bottom)) continue;
        // Native fallback text can span many lines. Locate the first visible
        // character rather than anchoring to the start of the entire paragraph.
        let low = 0, high = record.node.length - 1;
        while (low < high) {
          const mid = Math.floor((low + high) / 2);
          if (characterRect(record.node, mid).bottom <= bounds.top) low = mid + 1;
          else high = mid;
        }
        return {offset:record.start + low, top:characterRect(record.node, low).top - bounds.top};
      }
      return null;
    }

    function restorePosition(saved) {
      if (!saved) return;
      const [node, offset] = point(saved.offset);
      const top = characterRect(node, offset).top - scrollRoot.getBoundingClientRect().top;
      scrollRoot.scrollTop += top - saved.top;
    }

    function native(narrow) {
      root.classList.remove('paragraph-layout');
      root.classList.toggle('paragraph-narrow', narrow);
      records = [];
      root.replaceChildren();
      text(root, 0, source.length);
    }

    function supported(value) {
      // No dictionaries, bidi, control characters, unusual whitespace, or
      // script-specific rules. Native layout handles those unchanged.
      return Boolean(value) && !/^ | $| {2}/.test(value) &&
        /^[\p{Script=Latin}\p{Mark}\p{Punctuation} 0-9$+<=>^|~]*$/u.test(value);
    }

    function prepare(style) {
      const probe = document.createElement('span');
      probe.style.cssText = 'position:fixed;visibility:hidden;white-space:pre;width:max-content;letter-spacing:0;word-spacing:0;pointer-events:none';
      for (const property of ['fontFamily','fontSize','fontWeight','fontStyle','fontStretch','fontKerning','fontVariantLigatures','fontFeatureSettings','fontVariationSettings','textRendering']) {
        probe.style[property] = style[property];
      }
      root.append(probe);
      const measured = new Map();
      function measure(value) {
        if (!measured.has(value)) {
          probe.textContent = value;
          const result = probe.getBoundingClientRect().width;
          if (!Number.isFinite(result) || result <= 0) throw new Error('Unavailable font measurement');
          measured.set(value, result);
        }
        return measured.get(value);
      }
      try {
        let start = 0;
        return source.split(/(\r\n|\r|\n)/).map((value, index) => {
          const segment = {start, end:start + value.length, prepared:null, words:[]};
          start += value.length;
          if (index % 2 || !supported(value)) return segment;
          const matches = [...value.matchAll(/[^ ]+/g)];
          segment.words = matches.map(match => segment.start + match.index);
          segment.prepared = window.Justice.prepare(value, measure);
          return segment;
        });
      } finally {
        probe.remove();
      }
    }

    function compose(columnWidth) {
      const fragment = document.createDocumentFragment();
      let fitted = false;
      records = [];
      segments.forEach((segment, index) => {
        if (index % 2) {text(fragment, segment.start, segment.end); return;}
        const paragraph = document.createElement('span');
        paragraph.className = 'paragraph-segment';
        let lines = null;
        const prepared = segment.prepared;
        if (prepared && prepared.words.every((word, i) => prepared.widths[i + 1] - prepared.widths[i] <= columnWidth)) {
          try {
            const layout = window.Justice.solve(prepared, columnWidth);
            // A residual outside rounding tolerance is not a safe nowrap line.
            if (layout.lines.length && layout.lines.every(line => !line.hyphenated &&
              Number.isFinite(line.wordSpacing) && Number.isFinite(line.tracking) && line.residual >= -0.5)) {
              lines = layout.lines;
            }
          } catch { /* This segment retains native layout if solving fails. */ }
        }
        if (!lines) text(paragraph, segment.start, segment.end);
        else {
          paragraph.classList.add('paragraph-fitted');
          fitted = true;
          let cursor = segment.start;
          for (const line of lines) {
            const start = segment.words[line.start] + (line.startOffset || 0);
            const last = line.end - 1;
            const end = segment.words[last] + (line.endOffset ?? prepared.words[last].length);
            if (cursor < start) text(paragraph, cursor, start);
            const element = document.createElement('span');
            element.className = 'paragraph-line';
            element.dataset.sourceStart = start;
            element.dataset.sourceEnd = end;
            element.style.wordSpacing = `${line.wordSpacing}px`;
            element.style.letterSpacing = `${line.tracking}px`;
            element.style.marginLeft = `${-line.opening}px`;
            text(element, start, end);
            paragraph.append(element);
            cursor = end;
          }
          if (cursor < segment.end) text(paragraph, cursor, segment.end);
        }
        fragment.append(paragraph);
      });
      if (!fitted) {native(false); return;}
      root.classList.add('paragraph-layout');
      root.classList.remove('paragraph-narrow');
      root.replaceChildren(fragment);
    }

    function layout(force = false) {
      if (destroyed || source === null) return;
      const style = getComputedStyle(root);
      const nextWidth = root.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      if (nextWidth <= 0 || !root.getClientRects().length) return;
      const nextFont = ['font','fontKerning','fontVariantLigatures','fontFeatureSettings','fontVariationSettings','textRendering'].map(key => style[key]).join('|');
      if (!force && width === nextWidth && fontKey === nextFont) return;
      const selection = rememberSelection(), position = rememberPosition();
      width = nextWidth;
      const narrow = width < 20 * parseFloat(style.fontSize);
      try {
        if (!window.Justice || narrow || !window.Intl?.Segmenter) native(narrow);
        else {
          if (!segments || force || fontKey !== nextFont) segments = prepare(style);
          compose(width);
        }
      } catch {
        segments = null;
        native(narrow);
      }
      fontKey = nextFont;
      restoreSelection(selection);
      restorePosition(position);
      onLayout();
    }

    function schedule(force = false) {
      fontsChanged ||= force;
      if (frame || destroyed || source === null) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const forceLayout = fontsChanged;
        fontsChanged = false;
        layout(forceLayout);
      });
    }

    function copy(event) {
      if (source === null || !root.classList.contains('paragraph-layout') || !event.clipboardData) return;
      const selection = window.getSelection();
      if (!selection?.rangeCount || selection.isCollapsed) return;
      const parts = [];
      let intersects = false;
      for (let index = 0; index < selection.rangeCount; index++) {
        const range = selection.getRangeAt(index);
        if (!range.intersectsNode(root)) {parts.push(range.toString()); continue;}
        intersects = true;
        const start = sourceOffset(range.startContainer, range.startOffset);
        const end = sourceOffset(range.endContainer, range.endOffset);
        let before = '', after = '';
        if (start === null) {
          const prefix = range.cloneRange();
          prefix.setEndBefore(root);
          before = prefix.toString();
        }
        if (end === null) {
          const suffix = range.cloneRange();
          suffix.setStartAfter(root);
          after = suffix.toString();
        }
        parts.push(before + source.slice(start ?? 0, end ?? source.length) + after);
      }
      if (intersects) {
        event.clipboardData.setData('text/plain', parts.join('\n'));
        event.preventDefault();
      }
    }

    function clear() {
      cancelAnimationFrame(frame);
      frame = 0;
      fontsChanged = false;
      if (source !== null) root.textContent = source;
      source = segments = fontKey = null;
      width = -1;
      records = [];
      root.classList.remove('paragraph-layout','paragraph-narrow');
    }

    const observer = new ResizeObserver(() => schedule());
    observer.observe(root);
    const fontLoaded = () => schedule(true);
    document.fonts?.addEventListener('loadingdone', fontLoaded);
    document.fonts?.ready.then(() => {if (!destroyed) schedule(true);});
    document.addEventListener('copy', copy);

    return {
      setText(value) {
        if (destroyed) return;
        if (source === value) {layout(); return;}
        clear();
        source = value;
        native(false);
        layout();
      },
      clear,
      destroy() {
        clear();
        destroyed = true;
        observer.disconnect();
        document.fonts?.removeEventListener('loadingdone', fontLoaded);
        document.removeEventListener('copy', copy);
      },
    };
  }

  window.ParagraphLayout = {create};
})();
