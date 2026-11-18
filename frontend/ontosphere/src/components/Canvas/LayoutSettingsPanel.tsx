import React, { useState, useEffect } from 'react';
import { Layout } from 'lucide-react';
import { Slider } from '../ui/slider';
import { toast } from 'sonner';
import { useAppConfigStore } from '../../stores/appConfigStore';
import { useShallow } from 'zustand/react/shallow';

const LAYOUT_OPTIONS = [
  { type: 'horizontal',       label: 'Horizontal',       description: 'Left-to-right (Dagre)' },
  { type: 'vertical',         label: 'Vertical',         description: 'Top-to-bottom (Dagre)' },
  { type: 'elk-layered',      label: 'Layered',          description: 'Hierarchy (ELK)' },
  { type: 'elk-force',        label: 'Force',            description: 'Force-directed (ELK)' },
  { type: 'elk-stress',       label: 'Stress',           description: 'Dense graphs (ELK)' },
  { type: 'reactodia-default',label: 'Default',          description: 'Cola with overlap removal' },
];

interface LayoutSettingsPanelProps {
  open: boolean;
  onClose: () => void;
  onApplyLayout: () => void;
}

export const LayoutSettingsPanel: React.FC<LayoutSettingsPanelProps> = ({ open, onClose, onApplyLayout }) => {
  const { config, setCurrentLayout, setLayoutSpacing, setAutoApplyLayout } = useAppConfigStore(
    useShallow((s) => ({
      config: s.config,
      setCurrentLayout: s.setCurrentLayout,
      setLayoutSpacing: s.setLayoutSpacing,
      setAutoApplyLayout: s.setAutoApplyLayout,
    })),
  );

  const [tempSpacing, setTempSpacing] = useState<number>(config.layoutSpacing ?? 120);

  // Re-initialize the local slider value from the store each time the panel opens,
  // so the slider never shows a stale value from a previous session.
  useEffect(() => {
    if (!open) return;
    setTempSpacing(config.layoutSpacing ?? 120);
    // config.layoutSpacing intentionally omitted: we only want to reset when the panel opens,
    // not on every external spacing change while the panel is visible.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleSelectLayout = (type: string) => {
    setCurrentLayout(type);
    onApplyLayout();
    toast.success(`Layout: ${LAYOUT_OPTIONS.find(l => l.type === type)?.label ?? type}`);
  };

  const handleApply = () => {
    setLayoutSpacing(tempSpacing);
    onApplyLayout();
  };

  const handleReset = () => {
    setLayoutSpacing(120);
    setTempSpacing(120);
    onApplyLayout();
    toast.success('Spacing reset to 120px');
  };

  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-black/60 pt-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-sm max-h-[calc(100%-2rem)] overflow-y-auto rounded-lg border bg-background p-0 shadow-lg animate-in fade-in-0 zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-4 pt-4 pb-2">
          <h2 className="text-lg font-semibold">Layout Settings</h2>
          <button
            className="rounded-sm p-1.5 opacity-70 hover:opacity-100 hover:bg-accent transition-colors"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Algorithm list */}
        <div className="px-4 pb-2">
          <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', opacity: 0.5, marginBottom: 4 }}>
            Algorithm
          </div>
          {LAYOUT_OPTIONS.map((layout) => {
            const active = config.currentLayout === layout.type;
            return (
              <button
                key={layout.type}
                onClick={() => handleSelectLayout(layout.type)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  width: '100%',
                  padding: '5px 6px',
                  borderRadius: 6,
                  border: 'none',
                  background: active ? 'rgba(124, 92, 228, 0.12)' : 'transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
                className={active ? 'glass-btn--active' : ''}
              >
                <Layout style={{ width: 13, height: 13, flexShrink: 0, opacity: 0.6 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: active ? 600 : 400, color: 'var(--foreground)' }}>
                    {layout.label}
                  </div>
                  <div style={{ fontSize: 11, opacity: 0.5 }}>{layout.description}</div>
                </div>
                {active && (
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--primary)', flexShrink: 0 }} />
                )}
              </button>
            );
          })}
        </div>

        {/* Spacing */}
        <div className="border-t px-4 py-3">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', opacity: 0.5, whiteSpace: 'nowrap' }}>
              Spacing
            </div>
            <div
              style={{ flex: 1 }}
              onPointerUp={() => {
                setLayoutSpacing(tempSpacing);
                if (config.autoApplyLayout) onApplyLayout();
              }}
            >
              <Slider
                value={[tempSpacing]}
                onValueChange={([v]) => setTempSpacing(v)}
                min={50}
                max={500}
                step={10}
              />
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, opacity: 0.7, width: 36, textAlign: 'right' }}>
              {tempSpacing}
            </div>
          </div>
        </div>

        {/* Footer actions */}
        <div className="border-t flex items-center gap-1.5 px-4 py-3">
          <button
            className={`glass-btn${config.autoApplyLayout ? ' glass-btn--active' : ''}`}
            style={{ fontSize: 12, padding: '4px 10px' }}
            onClick={() => {
              const next = !config.autoApplyLayout;
              setAutoApplyLayout(next);
              toast.success(next ? 'Auto layout on' : 'Auto layout off');
            }}
            aria-pressed={config.autoApplyLayout}
          >
            Auto
          </button>
          <div style={{ flex: 1 }} />
          <button
            className="glass-btn"
            style={{ fontSize: 12, padding: '4px 10px' }}
            onClick={handleReset}
          >
            Reset
          </button>
          <button
            className="glass-btn glass-btn--active"
            style={{ fontSize: 12, padding: '4px 10px' }}
            onClick={handleApply}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
};
