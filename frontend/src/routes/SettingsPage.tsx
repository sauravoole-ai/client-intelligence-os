function SettingsPage() {
  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h2 className="page__title">Settings</h2>
          <p className="page__subtitle">A polished shell for future product controls and policy configuration.</p>
        </div>
      </div>

      <div className="grid grid--2">
        {[
          ['Organisation', 'Workspace identity and operating context'],
          ['Users and roles', 'Planned access controls and review permissions'],
          ['Intelligence policies', 'Fallback, evidence and review policy configuration'],
          ['Integrations', 'Secure connections for downstream operations'],
        ].map(([title, description]) => (
          <div key={title} className="card settings-card">
            <h3>{title}</h3>
            <p>{description}</p>
            <span className="badge badge--positive">Planned</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default SettingsPage;
