import { useEffect, useRef, useState } from "react";

export interface AvailableVariable {
  name: string;
  sourceNodeId: string;
  sourceNodeTitle: string;
}

interface VariablePickerProps {
  variables: AvailableVariable[];
  onInsert: (variableName: string) => void;
  disabled?: boolean;
}

/**
 * "插入变量" picker — mirrors n8n's dual-track variable referencing.
 * Lists every variable declared by upstream nodes; clicking one inserts
 * `{{variable}}` into the current field (appended to the existing value).
 */
export function VariablePicker({
  variables,
  onInsert,
  disabled = false,
}: VariablePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (disabled) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        className="inline-flex items-center gap-1 rounded-full border border-brand-300/30 bg-brand-300/10 px-2.5 py-1 text-xs font-semibold text-brand-100 transition hover:bg-brand-300/20"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span>{"{{ }}"}</span>
        <span>插入变量</span>
      </button>

      {open ? (
        <div className="absolute left-0 z-20 mt-1 max-h-56 w-56 overflow-y-auto rounded-lg border border-white/10 bg-surface-900/95 p-1.5 shadow-prism backdrop-blur-xl">
          {variables.length === 0 ? (
            <p className="px-3 py-2 text-xs text-slate-500">
              暂无可用变量。请先添加入口节点或上游节点。
            </p>
          ) : (
            variables.map((variable) => (
              <button
                className="block w-full rounded-md px-3 py-1.5 text-left transition hover:bg-brand-300/10"
                key={variable.name}
                onClick={() => {
                  onInsert(variable.name);
                  setOpen(false);
                }}
                type="button"
              >
                <span className="block text-xs font-semibold text-slate-100">
                  {"{{"}{variable.name}{"}}"}
                </span>
                <span className="block truncate text-[11px] text-slate-500">
                  来自：{variable.sourceNodeTitle}
                </span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
