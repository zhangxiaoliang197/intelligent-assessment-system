import React from 'react';
import { Layout } from 'lucide-react';

interface LayoutPopoverProps {
  onToggle: () => void;
}

export const LayoutPopover: React.FC<LayoutPopoverProps> = ({ onToggle }) => (
  <button
    className="glass-btn text-xs"
    title="Layout settings"
    onClick={onToggle}
  >
    <Layout className="h-3 w-3 shrink-0" />
    <span>Layout</span>
  </button>
);
