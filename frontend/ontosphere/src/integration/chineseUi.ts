/** Embed-only localization; never changes RDF literals, IRIs, query text or input values. */
import englishBundleText from '../../node_modules/@reactodia/workspace/i18n/translations/en.reactodia-translation.json?raw';
import type { ComponentProps } from 'react';
import { Workspace } from '@reactodia/workspace';
import { translateUi } from './translations-zh';

const english = JSON.parse(englishBundleText);
type TranslationBundle = NonNullable<ComponentProps<typeof Workspace>['translations']>[number];
export const chineseReactodia: TranslationBundle = Object.fromEntries(Object.entries(english).filter(([key]) => key !== '$schema').map(([section, values]) => [section,
  Object.fromEntries(Object.entries(values as Record<string, string | null>).map(([key, value]) => [key, typeof value === 'string' ? translateUi(value) : value])),
]));

export function installChineseUi() {
  document.documentElement.lang = 'zh-CN';
  document.title = '动态本体工作台 · 智能评估系统';
  const excluded = 'script,style,textarea,code,pre,[contenteditable="true"],.vg-card,.reactodia-link-label,.monaco-editor,.cm-editor';
  const attributes = ['title', 'aria-label', 'placeholder', 'alt', 'data-placeholder'];
  function text(node: Text) {
    if (!node.parentElement || node.parentElement.closest(excluded)) return;
    const translated = translateUi(node.data);
    if (translated !== node.data) node.data = translated;
  }
  function element(node: Element) {
    for (const name of attributes) {
      const original = node.getAttribute(name);
      if (original) { const translated = translateUi(original); if (translated !== original) node.setAttribute(name, translated); }
    }
  }
  function subtree(node: Node) {
    if (node.nodeType === Node.TEXT_NODE) { text(node as Text); return; }
    if (node instanceof Element) element(node);
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode instanceof Element) element(walker.currentNode);
      else text(walker.currentNode as Text);
    }
  }
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') text(record.target as Text);
      else if (record.type === 'attributes') element(record.target as Element);
      else record.addedNodes.forEach(subtree);
    }
  });
  subtree(document.body);
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: attributes });
  return () => observer.disconnect();
}
