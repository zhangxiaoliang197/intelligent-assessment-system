import { useEffect, useRef } from 'react';
import { X, FileText, Copy, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useState } from 'react';

/* ═══════════════════════════════════════════════════════════════
   Dark-theme Markdown components – full report styling
   ═══════════════════════════════════════════════════════════════ */
const mdComponents = {
  h1: ({ children, ...p }: any) => (
    <h1 {...p} className="text-2xl font-bold text-gray-50 mt-6 mb-4 pb-3 border-b border-cyan-500/20">
      {children}
    </h1>
  ),
  h2: ({ children, ...p }: any) => (
    <h2 {...p} className="text-xl font-bold text-gray-100 mt-5 mb-3 pb-2 border-b border-[var(--aegis-border)]">
      {children}
    </h2>
  ),
  h3: ({ children, ...p }: any) => (
    <h3 {...p} className="text-lg font-semibold text-gray-200 mt-4 mb-2">{children}</h3>
  ),
  h4: ({ children, ...p }: any) => (
    <h4 {...p} className="text-base font-semibold text-gray-300 mt-3 mb-1.5">{children}</h4>
  ),
  p: ({ children, ...p }: any) => (
    <p {...p} className="text-sm text-gray-300 mb-3 leading-relaxed">{children}</p>
  ),
  ul: ({ children, ...p }: any) => (
    <ul {...p} className="list-disc list-outside text-sm text-gray-300 mb-3 space-y-1.5 ml-5">{children}</ul>
  ),
  ol: ({ children, ...p }: any) => (
    <ol {...p} className="list-decimal list-outside text-sm text-gray-300 mb-3 space-y-1.5 ml-5">{children}</ol>
  ),
  li: ({ children, ...p }: any) => (
    <li {...p} className="text-sm text-gray-300 leading-relaxed">{children}</li>
  ),
  strong: ({ children, ...p }: any) => (
    <strong {...p} className="font-bold text-gray-100">{children}</strong>
  ),
  em: ({ children, ...p }: any) => (
    <em {...p} className="italic text-gray-400">{children}</em>
  ),
  code: ({ children, className, ...p }: any) => {
    const isInline = !className;
    return isInline ? (
      <code {...p} className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 text-xs font-mono border border-cyan-500/20">
        {children}
      </code>
    ) : (
      <code {...p} className={`block p-3 rounded-lg bg-[var(--aegis-surface)] text-cyan-300 text-xs font-mono border border-[var(--aegis-border)] overflow-x-auto ${className}`}>
        {children}
      </code>
    );
  },
  pre: ({ children, ...p }: any) => (
    <pre {...p} className="mb-3 rounded-lg overflow-hidden">{children}</pre>
  ),
  blockquote: ({ children, ...p }: any) => (
    <blockquote {...p} className="border-l-3 border-cyan-500/40 pl-4 py-1 my-3 text-gray-400 italic bg-cyan-500/5 rounded-r-lg">
      {children}
    </blockquote>
  ),
  table: ({ children, ...p }: any) => (
    <div className="overflow-x-auto mb-3">
      <table {...p} className="w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  th: ({ children, ...p }: any) => (
    <th {...p} className="text-left px-3 py-2 bg-[var(--aegis-surface)] text-gray-300 font-semibold border border-[var(--aegis-border)] text-xs">
      {children}
    </th>
  ),
  td: ({ children, ...p }: any) => (
    <td {...p} className="px-3 py-2 text-gray-400 border border-[var(--aegis-border)] text-xs">
      {children}
    </td>
  ),
  hr: (p: any) => (
    <hr {...p} className="border-[var(--aegis-border)] my-5" />
  ),
  a: ({ children, href, ...p }: any) => (
    <a {...p} href={href} className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2" target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

/* ═══════════════════════════════════════════════════════════════
   Modal Component
   ═══════════════════════════════════════════════════════════════ */
interface Props {
  content: string;
  title?: string;
  onClose: () => void;
}

export default function MarkdownModal({ content, title, onClose }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Close on overlay click
  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-6 animate-fade-in"
    >
      <div className="relative w-full max-w-3xl max-h-[85vh] flex flex-col rounded-2xl bg-[var(--aegis-bg)] border border-cyan-500/20 shadow-[0_0_60px_rgba(6,182,212,0.12)] overflow-hidden">

        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--aegis-border)] bg-[var(--aegis-surface)] shrink-0">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/15 flex items-center justify-center">
            <FileText className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-gray-200 truncate">
              {title || 'Investigation Report'}
            </h2>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">
              AI Agent Analysis · Rendered Markdown
            </p>
          </div>

          <button
            onClick={copyToClipboard}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-cyan-400 hover:bg-cyan-500/10 border border-[var(--aegis-border)] transition-colors"
            title="Copy markdown source"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied!' : 'Copy'}
          </button>

          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Rendered Markdown Body */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
