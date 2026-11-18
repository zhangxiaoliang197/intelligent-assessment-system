import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import manual from './README.zh-CN.md?raw';

export function ChineseManual({ section, onClose }: { section: string; onClose: () => void }) {
  const content = manual.split('\n## ').find(value => value.startsWith(section + '\n'))?.split('\n').slice(1).join('\n') || manual;
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [onClose]);
  return createPortal(<div className="fixed inset-0 flex items-center justify-center bg-black/30 p-6" style={{ zIndex: 2147483000 }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label={`使用文档：${section}`} className="w-full max-w-2xl rounded-xl border border-border bg-card text-foreground shadow-xl">
      <header className="flex items-center justify-between border-b border-border px-6 py-4"><h2 className="text-base font-semibold">{section}</h2><button onClick={onClose} aria-label="关闭使用文档" className="rounded-md px-3 py-1 hover:bg-muted">关闭</button></header>
      <div className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words px-6 py-5 text-sm leading-7">{content}</div>
    </section>
  </div>, document.body);
}
