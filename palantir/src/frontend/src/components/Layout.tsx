import { Outlet, NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Network,
  Map,
  ShieldAlert,
  Activity,
  Clock,
  Search,
  Building2,
  Users,
  Terminal,
  Waves,
  Info,
  ExternalLink,
  X,
  GraduationCap,
  Code2,
} from 'lucide-react';
import { useState } from 'react';
import SearchBar from './SearchBar';
import { useSignalR } from '../hooks/useSignalR';
import { useRiskCases } from '../hooks/useApi';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/command-center', icon: Terminal, label: 'Command Center' },
  { to: '/risk-propagation', icon: Waves, label: 'Risk Propagation' },
  { to: '/map', icon: Map, label: 'Geospatial' },
  { to: '/cases', icon: ShieldAlert, label: 'Risk Cases' },
  { to: '/events', icon: Activity, label: 'Events' },
  { to: '/facilities', icon: Building2, label: 'Facilities' },
  { to: '/persons', icon: Users, label: 'Persons' },
  { to: '/timeline', icon: Clock, label: 'Timeline' },
];

export default function Layout() {
  const [searchOpen, setSearchOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  useSignalR(); // Connect to real-time hub, auto-refresh queries on new events/cases
  const { data: cases } = useRiskCases();
  const activeCases = cases?.filter((c) => c.status === 'Open' || c.status === 'Investigating') ?? [];

  return (
    <div className="flex h-screen bg-[var(--aegis-bg)]">
      {/* Sidebar */}
      <aside className="w-56 bg-[var(--aegis-surface)] border-r border-[var(--aegis-border)] flex flex-col overflow-hidden">
        {/* Logo */}
        <div className="h-16 flex items-center px-4 gap-3 border-b border-[var(--aegis-border)]">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center flex-shrink-0">
            <Network className="w-5 h-5 text-white" />
          </div>
          <span className="text-lg font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent whitespace-nowrap">
            AEGIS
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center px-4 py-3 gap-3 text-sm transition-all duration-200 ${
                  isActive
                    ? 'text-cyan-400 bg-cyan-500/10 border-r-2 border-cyan-400'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'
                }`
              }
            >
              <item.icon className="w-5 h-5 flex-shrink-0" />
              <span className="whitespace-nowrap">
                {item.label}
              </span>
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-[var(--aegis-border)] space-y-2.5">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse flex-shrink-0" />
            <span className="text-xs text-gray-500 whitespace-nowrap">
              System Online
            </span>
          </div>
          <a
            href="https://jmfloreszazo.com"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-gray-500 hover:text-cyan-400 hover:bg-cyan-500/5 transition-colors group"
          >
            <Code2 className="w-3.5 h-3.5 flex-shrink-0" />
            <span className="text-[10px] font-medium truncate">jmfloreszazo.com</span>
            <ExternalLink className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
          </a>
          <button
            onClick={() => setAboutOpen(true)}
            className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-gray-600 hover:text-gray-400 hover:bg-white/5 transition-colors w-full"
          >
            <GraduationCap className="w-3.5 h-3.5 flex-shrink-0" />
            <span className="text-[10px]">About & Disclaimer</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-14 bg-[var(--aegis-surface)] border-b border-[var(--aegis-border)] flex items-center justify-between px-6">
          <h1 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Water Supply Intelligence Platform
          </h1>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSearchOpen(!searchOpen)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-colors text-sm"
            >
              <Search className="w-4 h-4" />
              <span>Search...</span>
              <kbd className="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">
                ⌘K
              </kbd>
            </button>
            <button
              onClick={() => { window.location.href = '/cases'; }}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 hover:bg-red-500/20 transition-colors cursor-pointer"
            >
              <ShieldAlert className="w-4 h-4 text-red-400" />
              <span className="text-xs text-red-400 font-medium">
                {activeCases.length} Active Cases
              </span>
            </button>
          </div>
        </header>

        {/* Search overlay */}
        {searchOpen && <SearchBar onClose={() => setSearchOpen(false)} />}

        {/* Page content */}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>

      {/* About & Disclaimer Modal */}
      {aboutOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setAboutOpen(false)}
        >
          <div
            className="w-full max-w-lg mx-4 bg-[var(--aegis-surface)] border border-[var(--aegis-border)] rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--aegis-border)]">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center">
                  <Network className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-gray-100">AEGIS Platform</h2>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider">Water Supply Intelligence</p>
                </div>
              </div>
              <button
                onClick={() => setAboutOpen(false)}
                className="w-8 h-8 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-500 hover:text-red-400 hover:border-red-500/50 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="px-6 py-5 space-y-5">
              {/* About the Author */}
              <div>
                <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2 mb-2">
                  <Code2 className="w-4 h-4 text-cyan-400" />
                  About the Author
                </h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  Developed by <strong className="text-cyan-400">José María Flores Zazo</strong> as
                  a technical exploration of knowledge-graph-driven intelligence platforms.
                </p>
                <a
                  href="https://jmfloreszazo.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 mt-2.5 px-4 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-sm font-medium hover:bg-cyan-500/20 hover:border-cyan-400/50 transition-all"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  jmfloreszazo.com
                </a>
              </div>

              {/* Disclaimer */}
              <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
                <h3 className="text-sm font-semibold text-amber-400 flex items-center gap-2 mb-2">
                  <GraduationCap className="w-4 h-4" />
                  Disclaimer — Educational & Study Purposes
                </h3>
                <p className="text-xs text-gray-400 leading-relaxed">
                  This project is a <strong className="text-gray-300">proof of concept</strong> created
                  exclusively for <strong className="text-gray-300">educational, research, and study purposes</strong>.
                  It is not intended for production use. All data, entities, events, and scenarios depicted
                  are entirely <strong className="text-gray-300">fictitious</strong> and do not represent
                  real individuals, organizations, or infrastructure.
                </p>
                <p className="text-xs text-gray-500 leading-relaxed mt-2">
                  The technologies demonstrated — including ontology-driven reasoning, knowledge graphs,
                  NL→Cypher translation, multi-agent orchestration, and risk propagation — are showcased
                  as a learning exercise in modern intelligence platform architecture.
                </p>
              </div>

              {/* Tech stack mini-summary */}
              <div className="flex flex-wrap gap-1.5">
                {['Neo4j', 'OpenSearch', 'Ollama', '.NET 10', 'React 19', 'Cytoscape.js', 'SignalR', 'OWL/TTL', 'Docker'].map((t) => (
                  <span key={t} className="px-2 py-0.5 rounded-full bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] text-[10px] text-gray-500">
                    {t}
                  </span>
                ))}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-[var(--aegis-border)] bg-[var(--aegis-surface-2)]/50">
              <p className="text-[10px] text-gray-600 text-center">
                © 2026 José María Flores Zazo · For educational and study purposes only
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
