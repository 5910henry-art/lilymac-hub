

cd ~/lilymac-hub/frontend

cat > /tmp/patch_h2h.py <<'PY'
from pathlib import Path
import re
import shutil

path = Path("src/user/H2H.jsx")

if not path.exists():
    raise SystemExit(f"File not found: {path}")

source = path.read_text(encoding="utf-8")

backup = path.with_suffix(".jsx.backup")
shutil.copy2(path, backup)

new_component = r'''function TeamSelector({
  label,
  team,
  value,
  search,
  setSearch,
  options,
  onChange,
}) {
  const [isOpen, setIsOpen] = useState(false);

  const visibleOptions = useMemo(() => {
    const query = search.trim().toLowerCase();

    const filtered = options.filter((item) =>
      String(item?.name || "")
        .toLowerCase()
        .includes(query)
    );

    if (
      team &&
      !filtered.some(
        (item) => String(item.id) === String(team.id)
      )
    ) {
      return [team, ...filtered];
    }

    return filtered;
  }, [options, search, team]);

  const handleSelect = (selectedValue) => {
    onChange(String(selectedValue));
    setSearch("");
    setIsOpen(false);
  };

  return (
    <div className="relative min-w-0">
      <label className="
        mb-2 block text-xs font-bold uppercase
        tracking-wider text-slate-400
      ">
        {label}
      </label>

      <div className="
        mb-2 flex min-h-[64px] items-center gap-3
        rounded-xl border border-blue-100
        bg-blue-50/50 px-3 py-2
      ">
        <div className="
          flex h-10 w-10 flex-shrink-0 items-center
          justify-center rounded-full bg-white shadow-sm
        ">
          <img
            src={
              team?.logo ||
              team?.crest ||
              PLACEHOLDER
            }
            alt=""
            className="h-8 w-8 object-contain"
            onError={(event) => {
              event.currentTarget.src = PLACEHOLDER;
            }}
          />
        </div>

        <div className="min-w-0 flex-1">
          <p className="
            text-[10px] font-bold uppercase
            tracking-wide text-blue-500
          ">
            Selected {label}
          </p>

          <p className="
            truncate text-sm font-black text-slate-800
          ">
            {team?.name || "Choose a team"}
          </p>
        </div>

        <span className="
          flex h-6 w-6 items-center justify-center
          rounded-full bg-emerald-100 text-xs text-emerald-600
        ">
          ✓
        </span>
      </div>

      <div className="relative">
        <input
          type="text"
          value={search}
          onFocus={() => setIsOpen(true)}
          onChange={(event) => {
            setSearch(event.target.value);
            setIsOpen(true);
          }}
          placeholder={`Search ${label.toLowerCase()}...`}
          className="
            w-full rounded-xl border border-slate-200
            bg-white px-3 py-3 pr-10 text-sm
            text-slate-700 shadow-sm outline-none
            transition focus:border-blue-500
            focus:ring-2 focus:ring-blue-500/20
          "
        />

        <span className="
          pointer-events-none absolute right-3 top-1/2
          -translate-y-1/2 text-slate-400
        ">
          🔍
        </span>
      </div>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />

          <div className="
            absolute left-0 right-0 z-20 mt-2
            max-h-64 overflow-y-auto rounded-xl
            border border-slate-200 bg-white p-1 shadow-xl
          ">
            {visibleOptions.length > 0 ? (
              visibleOptions.map((item) => {
                const isSelected =
                  String(item.id) === String(value);

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleSelect(item.id)}
                    className={`
                      flex w-full items-center gap-3
                      rounded-lg px-3 py-2.5 text-left
                      transition
                      ${
                        isSelected
                          ? "bg-blue-50 text-blue-700"
                          : "text-slate-700 hover:bg-slate-50"
                      }
                    `}
                  >
                    <img
                      src={
                        item.logo ||
                        item.crest ||
                        PLACEHOLDER
                      }
                      alt=""
                      className="h-8 w-8 object-contain"
                      onError={(event) => {
                        event.currentTarget.src = PLACEHOLDER;
                      }}
                    />

                    <span className="
                      min-w-0 flex-1 truncate
                      text-sm font-semibold
                    ">
                      {item.name}
                    </span>

                    {isSelected && (
                      <span className="text-blue-600">
                        ✓
                      </span>
                    )}
                  </button>
                );
              })
            ) : (
              <div className="
                px-3 py-6 text-center text-sm text-slate-400
              ">
                No teams found
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}'''

pattern = (
    r'function TeamSelector\(\{.*?\n\}\n\n'
    r'/\* ={3,}={0,} TEAM BANNER'
)

replacement = (
    new_component
    + '\n\n'
    + '/* =========================================================\n'
    + '   TEAM BANNER'
)

updated, count = re.subn(
    pattern,
    replacement,
    source,
    count=1,
    flags=re.DOTALL,
)

if count != 1:
    raise SystemExit(
        "TeamSelector not found. No changes saved."
    )

path.write_text(updated, encoding="utf-8")

print("H2H.jsx patched successfully.")
print(f"Backup: {backup}")
PY

python /tmp/patch_h2h.py

