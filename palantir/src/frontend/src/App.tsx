import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './components/Dashboard';
import GraphExplorer from './components/GraphExplorer';
import MapView from './components/MapView';
import CasesView from './components/CasesView';
import EventsView from './components/EventsView';
import TimelineView from './components/TimelineView';
import FacilitiesView from './components/FacilitiesView';
import PersonsView from './components/PersonsView';
import EntityInvestigation from './components/EntityInvestigation';
import CommandCenter from './components/CommandCenter';
import RiskPropagation from './components/RiskPropagation';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="graph" element={<GraphExplorer />} />
        <Route path="graph/:nodeId" element={<GraphExplorer />} />
        <Route path="map" element={<MapView />} />
        <Route path="cases" element={<CasesView />} />
        <Route path="events" element={<EventsView />} />
        <Route path="facilities" element={<FacilitiesView />} />
        <Route path="persons" element={<PersonsView />} />
        <Route path="timeline" element={<TimelineView />} />
        <Route path="investigate/:entityType/:entityId" element={<EntityInvestigation />} />
        <Route path="command-center" element={<CommandCenter />} />
        <Route path="risk-propagation" element={<RiskPropagation />} />
      </Route>
    </Routes>
  );
}
