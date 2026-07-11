import { useState, useContext, useEffect } from "react";
import { ThemeContext } from "../App";

export default function GlobalSettingsModal({ onClose }) {
  const { settings, saveSettings } = useContext(ThemeContext);
  const [tempSettings, setTempSettings] = useState({ ...settings });

  // Close on ESC
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  const handleSave = () => {
    saveSettings(tempSettings);
    onClose();
  };

  const handleDiscard = () => {
    onClose();
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      onClick={handleBackdrop}
    >
      <div
        className="bg-surface border border-outline-variant w-full max-w-md rounded-xl shadow-2xl overflow-hidden flex flex-col"
        style={{ animation: "modalIn 0.18s ease-out" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant bg-surface">
          <div>
            <h2 className="font-code text-xs font-bold text-on-surface uppercase tracking-wider flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-primary">settings</span>
              Global Settings
            </h2>
          </div>
          <button
            onClick={handleDiscard}
            className="text-on-surface-variant hover:text-primary transition-colors p-1 rounded-md hover:bg-surface-container"
            aria-label="Close settings"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-6 flex flex-col gap-6 bg-surface">
          {/* Theme Option */}
          <div className="flex flex-col gap-2">
            <label className="font-code text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Theme Mode
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setTempSettings({ ...tempSettings, theme: "dark" })}
                className={`py-2.5 px-4 rounded-lg font-code text-xs font-bold border transition-all flex items-center justify-center gap-2 cursor-pointer ${
                  tempSettings.theme === "dark"
                    ? "bg-primary text-on-primary border-primary shadow-sm"
                    : "bg-surface-container hover:bg-surface-container-high border-outline-variant text-on-surface"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">dark_mode</span>
                Dark
              </button>
              <button
                type="button"
                onClick={() => setTempSettings({ ...tempSettings, theme: "light" })}
                className={`py-2.5 px-4 rounded-lg font-code text-xs font-bold border transition-all flex items-center justify-center gap-2 cursor-pointer ${
                  tempSettings.theme === "light"
                    ? "bg-primary text-on-primary border-primary shadow-sm"
                    : "bg-surface-container hover:bg-surface-container-high border-outline-variant text-on-surface"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">light_mode</span>
                Light
              </button>
            </div>
          </div>

          {/* Contribution Graph Color Option */}
          <div className="flex flex-col gap-2">
            <label className="font-code text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Contribution Color
            </label>
            <div className="grid grid-cols-4 gap-2">
              {[
                { name: "Green", value: "green", bgClass: "bg-green-500" },
                { name: "Blue", value: "blue", bgClass: "bg-blue-500" },
                { name: "Orange", value: "orange", bgClass: "bg-orange-500" },
                { name: "Yellow", value: "yellow", bgClass: "bg-yellow-500" }
              ].map((color) => {
                const isSelected = tempSettings.contributionColor === color.value;
                return (
                  <button
                    key={color.value}
                    type="button"
                    onClick={() => setTempSettings({ ...tempSettings, contributionColor: color.value })}
                    className={`flex flex-col items-center gap-1.5 p-2 rounded-lg border transition-all hover:bg-surface-container cursor-pointer ${
                      isSelected
                        ? "border-primary bg-surface-container-high shadow-sm"
                        : "border-outline-variant/40 bg-surface/10"
                    }`}
                  >
                    <div className={`w-6 h-6 rounded-full ${color.bgClass} border border-black/20`} />
                    <span className="text-[10px] font-code font-medium text-on-surface">
                      {color.name}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-outline-variant flex items-center justify-end gap-3 bg-surface">
          <button
            onClick={handleDiscard}
            className="h-9 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-xs font-bold rounded-lg transition-all active:scale-95 cursor-pointer"
          >
            Discard Changes
          </button>
          <button
            onClick={handleSave}
            className="h-9 px-4 bg-primary hover:bg-primary-container text-on-primary font-code text-xs font-bold rounded-lg transition-all shadow-sm shadow-primary/20 hover:shadow-primary/40 active:scale-95 cursor-pointer"
          >
            Save Changes
          </button>
        </div>
      </div>
      <style>{`
        @keyframes modalIn {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to   { opacity: 1; transform: translateY(0)    scale(1);    }
        }
      `}</style>
    </div>
  );
}
