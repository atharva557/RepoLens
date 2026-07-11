import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

export default function Status() {
  const [testData, setTestData] = useState(null);
  const [configData, setConfigData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      getJSON("/test").catch(e => ({ error: String(e) })),
      getJSON("/config").catch(e => ({ error: String(e) }))
    ]).then(([test, config]) => {
      setTestData(test);
      setConfigData(config);
      setLoading(false);
    }).catch(e => {
      setError(String(e));
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full motion-safe:animate-spin"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-on-surface p-8 max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold mb-2">System Status</h1>
        <p className="text-on-surface-variant text-sm font-code">
          Internal admin view for backend health and config.
        </p>
      </div>

      {error && (
        <div className="bg-error-container/20 border border-error-container text-error p-4 rounded-lg font-code text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* /test Endpoint */}
        <section className="bg-surface-container border border-outline-variant rounded-xl overflow-hidden">
          <div className="bg-surface-container-high px-4 py-3 border-b border-outline-variant/50">
            <h2 className="font-code text-sm font-bold uppercase tracking-wider text-primary">GET /test</h2>
          </div>
          <div className="p-4 overflow-x-auto">
            <pre className="text-[11px] font-code text-on-surface-variant">
              {testData ? JSON.stringify(testData, null, 2) : "No data"}
            </pre>
          </div>
        </section>

        {/* /config Endpoint */}
        <section className="bg-surface-container border border-outline-variant rounded-xl overflow-hidden">
          <div className="bg-surface-container-high px-4 py-3 border-b border-outline-variant/50">
            <h2 className="font-code text-sm font-bold uppercase tracking-wider text-primary">GET /config</h2>
          </div>
          <div className="p-4 overflow-x-auto">
            <pre className="text-[11px] font-code text-on-surface-variant">
              {configData ? JSON.stringify(configData, null, 2) : "No data"}
            </pre>
          </div>
        </section>
      </div>
    </div>
  );
}
