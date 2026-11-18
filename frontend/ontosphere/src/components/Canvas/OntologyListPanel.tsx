import React, { useEffect } from 'react';
import { toast } from 'sonner';
import { useAppConfigStore } from '../../stores/appConfigStore';
import { useOntologyStore } from '../../stores/ontologyStore';

interface OntologyListPanelProps {
  open: boolean;
  onClose: () => void;
}

const normalizeOntUrl = (u: string) => {
  try { return new URL(u.trim()).toString().replace(/[/#]+$/, '').replace(/^http:\/\//i, 'https://'); }
  catch { return u.trim().replace(/[/#]+$/, '').replace(/^http:\/\//i, 'https://'); }
};

export const OntologyListPanel: React.FC<OntologyListPanelProps> = ({ open, onClose }) => {
  const config = useAppConfigStore((s) => s.config);
  const addAdditionalOntology = useAppConfigStore((s) => s.addAdditionalOntology);
  const removeAdditionalOntology = useAppConfigStore((s) => s.removeAdditionalOntology);
  const additionalOntologies = useAppConfigStore((s) => s.config.additionalOntologies ?? []);
  const loadedOntologies = useOntologyStore((s) => s.loadedOntologies ?? []);
  const removeLoadedOntology = useOntologyStore((s) => s.removeLoadedOntology);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-black/60 pt-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-lg max-h-[calc(100%-2rem)] overflow-y-auto rounded-lg border bg-background p-6 shadow-lg animate-in fade-in-0 zoom-in-95 duration-200">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Loaded Ontologies</h2>
          <button
            className="rounded-sm p-1.5 opacity-70 hover:opacity-100 hover:bg-accent transition-colors"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        {loadedOntologies.length > 0 ? (
          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {loadedOntologies.map((ont: any, idx: number) => {
              const ontologyUrl = ont?.url || ont?.uri;
              const normUrl = ontologyUrl ? normalizeOntUrl(ontologyUrl) : '';
              const inAutoloadConfig = normUrl && additionalOntologies.some(
                (u) => normalizeOntUrl(u) === normUrl
              );
              const isAutoSource = ont?.source === 'fetched' || ont?.source === 'auto';
              const isAutoloaded = !!(inAutoloadConfig || isAutoSource);
              const isCore = ont?.source === 'auto';
              return (
                <div key={idx} className="border-b pb-2 last:border-0">
                  <div className="flex justify-between items-start gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm">{ont?.name || 'Unknown'}</div>
                      <div className="text-xs text-muted-foreground truncate">{ontologyUrl || 'No URI'}</div>
                      <div className="text-xs mt-1 flex items-center gap-1">
                        {ont?.loadStatus === 'fail'
                          ? <span className="text-red-500" title={ont?.loadError}>Failed</span>
                          : ont?.loadStatus === 'pending'
                          ? <span className="text-muted-foreground">Loading…</span>
                          : <span className="text-green-600">Loaded</span>
                        }
                        {isAutoloaded && <span className="text-muted-foreground">· autoload</span>}
                        {isCore && <span className="text-muted-foreground">· core</span>}
                      </div>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      {!isCore && ontologyUrl && (
                        isAutoloaded ? (
                          <button
                            className="glass-btn"
                            style={{ fontSize: 12, padding: '3px 8px' }}
                            onClick={() => {
                              const exactEntry = additionalOntologies.find(u => normalizeOntUrl(u) === normUrl);
                              removeAdditionalOntology(exactEntry ?? ontologyUrl);
                              toast.success(`Removed ${ont?.name || 'ontology'} from autoload`);
                            }}
                          >
                            Remove from autoload
                          </button>
                        ) : (
                          <button
                            className="glass-btn"
                            style={{ fontSize: 12, padding: '3px 8px' }}
                            onClick={() => {
                              addAdditionalOntology(ontologyUrl);
                              toast.success(`Added ${ont?.name || 'ontology'} to autoload`);
                            }}
                          >
                            Add to autoload
                          </button>
                        )
                      )}
                      {config?.persistedAutoload && !isCore && (
                        <button
                          className="glass-btn glass-btn--status-error"
                          style={{ fontSize: 12, padding: '3px 8px' }}
                          onClick={() => {
                            if (ontologyUrl) {
                              removeLoadedOntology(ontologyUrl);
                              toast.success(`Unloaded ${ont?.name || 'ontology'}`);
                            }
                          }}
                        >
                          Unload
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No ontologies loaded</p>
        )}
      </div>
    </div>
  );
};
