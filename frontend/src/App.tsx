import { Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/AppShell';
import OverviewPage from './routes/OverviewPage';
import ClientsPage from './routes/ClientsPage';
import NewAnalysisPage from './routes/NewAnalysisPage';
import ReviewQueuePage from './routes/ReviewQueuePage';
import AuditPage from './routes/AuditPage';
import SettingsPage from './routes/SettingsPage';
import ClientWorkspacePage from './routes/ClientWorkspacePage';

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/clients" element={<ClientsPage />} />
        <Route path="/clients/:clientId" element={<ClientWorkspacePage />} />
        <Route path="/new-analysis" element={<NewAnalysisPage />} />
        <Route path="/review-queue" element={<ReviewQueuePage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </AppShell>
  );
}

export default App;
