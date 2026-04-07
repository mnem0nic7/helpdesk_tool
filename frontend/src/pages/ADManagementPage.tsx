import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, {
  type ADUser,
  type ADGroup,
  type ADComputer,
  type ADOU,
  type CreateADUserRequest,
  type CreateADGroupRequest,
} from "../lib/api.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function badge(enabled: boolean) {
  return enabled ? (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Enabled</span>
  ) : (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Disabled</span>
  );
}

function ouLabel(dn: string): string {
  return dn
    .split(",")
    .filter((p) => p.trim().toUpperCase().startsWith("OU=") || p.trim().toUpperCase().startsWith("DC="))
    .map((p) => p.split("=")[1] ?? p)
    .join(" › ");
}

type Tab = "users" | "groups" | "computers" | "ous";

// ---------------------------------------------------------------------------
// Shared search bar
// ---------------------------------------------------------------------------

function SearchBar({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="relative">
      <svg
        className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m21 21-4.35-4.35" />
      </svg>
      <input
        type="search"
        className="w-full rounded-md border border-slate-200 py-2 pl-8 pr-3 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        placeholder={placeholder ?? "Search…"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide-over panel
// ---------------------------------------------------------------------------

function Panel({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="fixed inset-0 bg-black/20" onClick={onClose} />
      <div className="relative ml-auto flex h-full w-full max-w-xl flex-col bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-800">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal dialog
// ---------------------------------------------------------------------------

function Modal({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-800">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field row
// ---------------------------------------------------------------------------

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-2 border-b border-slate-100 py-2 text-sm last:border-0">
      <span className="font-medium text-slate-500">{label}</span>
      <span className="break-all text-slate-800">{value ?? "—"}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

function Pagination({
  page,
  total,
  limit,
  onChange,
}: {
  page: number;
  total: number;
  limit: number;
  onChange: (p: number) => void;
}) {
  const pages = Math.ceil(total / limit);
  if (pages <= 1) return null;
  return (
    <div className="flex items-center gap-2 pt-3 text-sm text-slate-600">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40 hover:bg-slate-50"
      >
        ‹
      </button>
      <span>
        Page {page} of {pages} ({total} total)
      </span>
      <button
        onClick={() => onChange(page + 1)}
        disabled={page >= pages}
        className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40 hover:bg-slate-50"
      >
        ›
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------

function UsersTab({ ous }: { ous: ADOU[] }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ADUser | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showResetPw, setShowResetPw] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showMove, setShowMove] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["ad-users", q, page],
    queryFn: () => api.listADUsers({ q, page, limit: 50 }),
  });

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["ad-users"] });
    if (selected) qc.invalidateQueries({ queryKey: ["ad-user", selected.sam_account_name] });
  }, [qc, selected]);

  const enableMut = useMutation({
    mutationFn: (sam: string) => api.enableADUser(sam),
    onSuccess: (updated) => { setSelected(updated); invalidate(); },
  });
  const disableMut = useMutation({
    mutationFn: (sam: string) => api.disableADUser(sam),
    onSuccess: (updated) => { setSelected(updated); invalidate(); },
  });
  const unlockMut = useMutation({
    mutationFn: (sam: string) => api.unlockADUser(sam),
    onSuccess: (updated) => { setSelected(updated); invalidate(); },
  });
  const deleteMut = useMutation({
    mutationFn: (sam: string) => api.deleteADUser(sam),
    onSuccess: () => { setSelected(null); invalidate(); },
  });

  function UserDetailPanel() {
    if (!selected) return null;
    return (
      <Panel title={selected.display_name || selected.sam_account_name} open onClose={() => setSelected(null)}>
        <div className="mb-4 flex flex-wrap gap-2">
          {badge(selected.flags.enabled)}
          {selected.flags.locked && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Locked</span>
          )}
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          {selected.flags.enabled ? (
            <button
              onClick={() => disableMut.mutate(selected.sam_account_name)}
              className="rounded bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
            >
              Disable
            </button>
          ) : (
            <button
              onClick={() => enableMut.mutate(selected.sam_account_name)}
              className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
            >
              Enable
            </button>
          )}
          {selected.flags.locked && (
            <button
              onClick={() => unlockMut.mutate(selected.sam_account_name)}
              className="rounded bg-amber-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-600"
            >
              Unlock
            </button>
          )}
          <button
            onClick={() => setShowResetPw(true)}
            className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
          >
            Reset Password
          </button>
          <button
            onClick={() => setShowEdit(true)}
            className="rounded border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Edit Attributes
          </button>
          <button
            onClick={() => setShowMove(true)}
            className="rounded border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Move
          </button>
          <button
            onClick={() => {
              if (confirm(`Delete user ${selected.sam_account_name}? This cannot be undone.`)) {
                deleteMut.mutate(selected.sam_account_name);
              }
            }}
            className="rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700"
          >
            Delete
          </button>
        </div>

        <Field label="Login name" value={selected.sam_account_name} />
        <Field label="UPN" value={selected.upn} />
        <Field label="Email" value={selected.email} />
        <Field label="Phone" value={selected.phone} />
        <Field label="Mobile" value={selected.mobile} />
        <Field label="Title" value={selected.title} />
        <Field label="Department" value={selected.department} />
        <Field label="Company" value={selected.company} />
        <Field label="Employee ID" value={selected.employee_id} />
        <Field label="Manager" value={selected.manager_dn ? ouLabel(selected.manager_dn) : "—"} />
        <Field label="Description" value={selected.description} />
        <Field label="Bad pwd count" value={selected.bad_pwd_count} />
        <Field label="Last logon" value={fmt(selected.last_logon)} />
        <Field label="Pwd last set" value={fmt(selected.pwd_last_set)} />
        <Field label="Account expires" value={fmt(selected.account_expires)} />
        <Field label="Created" value={fmt(selected.when_created)} />
        <Field label="Changed" value={fmt(selected.when_changed)} />
        <Field label="OU" value={ouLabel(selected.dn)} />

        {selected.member_of.length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-slate-500">Member of ({selected.member_of.length})</p>
            <ul className="space-y-0.5">
              {selected.member_of.map((dn) => (
                <li key={dn} className="truncate rounded bg-slate-50 px-2 py-1 text-xs text-slate-700">
                  {ouLabel(dn)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Panel>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="w-72">
          <SearchBar value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search users…" />
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          + New User
        </button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-slate-400">Loading…</div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">Login</th>
                <th className="pb-2 pr-4">Email</th>
                <th className="pb-2 pr-4">Dept</th>
                <th className="pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((u) => (
                <tr
                  key={u.dn}
                  onClick={() => setSelected(u)}
                  className="cursor-pointer border-b border-slate-100 hover:bg-slate-50"
                >
                  <td className="py-2 pr-4 font-medium text-slate-800">{u.display_name || u.sam_account_name}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-slate-600">{u.sam_account_name}</td>
                  <td className="py-2 pr-4 text-slate-600">{u.email || "—"}</td>
                  <td className="py-2 pr-4 text-slate-500">{u.department || "—"}</td>
                  <td className="py-2">{badge(u.flags.enabled)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && (
            <Pagination page={data.page} total={data.total} limit={data.limit} onChange={setPage} />
          )}
        </>
      )}

      <UserDetailPanel />

      {showCreate && <CreateUserModal ous={ous} onClose={() => setShowCreate(false)} onCreated={(u) => { setShowCreate(false); setSelected(u); invalidate(); }} />}
      {showResetPw && selected && (
        <ResetPasswordModal
          sam={selected.sam_account_name}
          onClose={() => setShowResetPw(false)}
          onDone={() => setShowResetPw(false)}
        />
      )}
      {showEdit && selected && (
        <EditUserModal
          user={selected}
          onClose={() => setShowEdit(false)}
          onSaved={(u) => { setShowEdit(false); setSelected(u); invalidate(); }}
        />
      )}
      {showMove && selected && (
        <MoveModal
          ous={ous}
          onClose={() => setShowMove(false)}
          onMove={(ouDn) => {
            api.moveADUser(selected.sam_account_name, ouDn).then((u) => {
              setShowMove(false);
              setSelected(u);
              invalidate();
            });
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create user modal
// ---------------------------------------------------------------------------

function CreateUserModal({
  ous,
  onClose,
  onCreated,
}: {
  ous: ADOU[];
  onClose: () => void;
  onCreated: (u: ADUser) => void;
}) {
  const [form, setForm] = useState<CreateADUserRequest>({
    sam: "",
    upn: "",
    display_name: "",
    given_name: "",
    surname: "",
    ou_dn: ous[0]?.dn ?? "",
    password: "",
    email: "",
    title: "",
    department: "",
    description: "",
  });
  const [error, setError] = useState("");

  const mut = useMutation({
    mutationFn: () => api.createADUser(form),
    onSuccess: onCreated,
    onError: (e: Error) => setError(e.message),
  });

  function f(k: keyof CreateADUserRequest, v: string) {
    setForm((p) => ({ ...p, [k]: v }));
  }

  return (
    <Modal title="Create User" open onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs font-medium text-slate-600">
            First name *
            <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.given_name} onChange={(e) => f("given_name", e.target.value)} />
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Last name *
            <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.surname} onChange={(e) => f("surname", e.target.value)} />
          </label>
        </div>
        <label className="block text-xs font-medium text-slate-600">
          Display name *
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.display_name} onChange={(e) => f("display_name", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Login (sAMAccountName) *
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 font-mono text-sm" value={form.sam} onChange={(e) => f("sam", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          UPN *
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 font-mono text-sm" value={form.upn} onChange={(e) => f("upn", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          OU (parent container) *
          <select className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.ou_dn} onChange={(e) => f("ou_dn", e.target.value)}>
            {ous.map((ou) => <option key={ou.dn} value={ou.dn}>{ouLabel(ou.dn)}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Password (requires LDAPS)
          <input type="password" className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.password ?? ""} onChange={(e) => f("password", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Email
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.email ?? ""} onChange={(e) => f("email", e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs font-medium text-slate-600">
            Title
            <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.title ?? ""} onChange={(e) => f("title", e.target.value)} />
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Department
            <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.department ?? ""} onChange={(e) => f("department", e.target.value)} />
          </label>
        </div>

        {error && <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="rounded border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !form.sam || !form.display_name || !form.ou_dn}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {mut.isPending ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Reset password modal
// ---------------------------------------------------------------------------

function ResetPasswordModal({ sam, onClose, onDone }: { sam: string; onClose: () => void; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [mustChange, setMustChange] = useState(true);
  const [error, setError] = useState("");

  const mut = useMutation({
    mutationFn: () => api.resetADPassword(sam, pw, mustChange),
    onSuccess: onDone,
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Modal title={`Reset Password — ${sam}`} open onClose={onClose}>
      <div className="space-y-3">
        <label className="block text-xs font-medium text-slate-600">
          New password
          <input type="password" autoFocus className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
          Require password change at next logon
        </label>
        <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Password reset requires LDAPS (AD_USE_SSL=true). The request will fail over plain LDAP.
        </p>
        {error && <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="rounded border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || pw.length < 1}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {mut.isPending ? "Resetting…" : "Reset Password"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Edit user attributes modal
// ---------------------------------------------------------------------------

function EditUserModal({ user, onClose, onSaved }: { user: ADUser; onClose: () => void; onSaved: (u: ADUser) => void }) {
  const [attrs, setAttrs] = useState<Record<string, string>>({
    displayName: user.display_name,
    givenName: user.given_name,
    sn: user.surname,
    mail: user.email,
    telephoneNumber: user.phone,
    mobile: user.mobile,
    title: user.title,
    department: user.department,
    company: user.company,
    description: user.description,
    streetAddress: user.street,
    l: user.city,
    st: user.state,
    postalCode: user.postal_code,
    co: user.country,
    employeeID: user.employee_id,
  });
  const [error, setError] = useState("");

  const mut = useMutation({
    mutationFn: () => api.updateADUser(user.sam_account_name, attrs),
    onSuccess: onSaved,
    onError: (e: Error) => setError(e.message),
  });

  function f(k: string, v: string) {
    setAttrs((p) => ({ ...p, [k]: v }));
  }

  const fields: [string, string, string][] = [
    ["displayName", "Display name", ""],
    ["givenName", "First name", ""],
    ["sn", "Last name", ""],
    ["mail", "Email", ""],
    ["telephoneNumber", "Phone", ""],
    ["mobile", "Mobile", ""],
    ["title", "Title", ""],
    ["department", "Department", ""],
    ["company", "Company", ""],
    ["employeeID", "Employee ID", ""],
    ["description", "Description", ""],
    ["streetAddress", "Street", ""],
    ["l", "City", ""],
    ["st", "State", ""],
    ["postalCode", "Postal code", ""],
    ["co", "Country", ""],
  ];

  return (
    <Modal title={`Edit — ${user.sam_account_name}`} open onClose={onClose}>
      <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">
        {fields.map(([k, label]) => (
          <label key={k} className="block text-xs font-medium text-slate-600">
            {label}
            <input
              className="mt-0.5 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
              value={attrs[k] ?? ""}
              onChange={(e) => f(k, e.target.value)}
            />
          </label>
        ))}
      </div>
      {error && <p className="mt-2 rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className="rounded border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
        <button onClick={() => mut.mutate()} disabled={mut.isPending} className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {mut.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Move modal (shared for users/groups)
// ---------------------------------------------------------------------------

function MoveModal({ ous, onClose, onMove }: { ous: ADOU[]; onClose: () => void; onMove: (dn: string) => void }) {
  const [ouDn, setOuDn] = useState(ous[0]?.dn ?? "");
  return (
    <Modal title="Move to OU" open onClose={onClose}>
      <label className="block text-xs font-medium text-slate-600">
        Destination OU
        <select className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={ouDn} onChange={(e) => setOuDn(e.target.value)}>
          {ous.map((ou) => <option key={ou.dn} value={ou.dn}>{ouLabel(ou.dn)}</option>)}
        </select>
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className="rounded border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
        <button onClick={() => onMove(ouDn)} disabled={!ouDn} className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">Move</button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Groups tab
// ---------------------------------------------------------------------------

function GroupsTab({ ous }: { ous: ADOU[] }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ADGroup | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [addMemberDn, setAddMemberDn] = useState("");
  const [addMemberError, setAddMemberError] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["ad-groups", q, page],
    queryFn: () => api.listADGroups({ q, page, limit: 50 }),
  });

  const { data: groupDetail } = useQuery({
    queryKey: ["ad-group-detail", selected?.sam_account_name],
    queryFn: () => api.getADGroup(selected!.sam_account_name),
    enabled: !!selected,
  });

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["ad-groups"] });
    if (selected) qc.invalidateQueries({ queryKey: ["ad-group-detail", selected.sam_account_name] });
  }, [qc, selected]);

  const deleteMut = useMutation({
    mutationFn: (sam: string) => api.deleteADGroup(sam),
    onSuccess: () => { setSelected(null); invalidate(); },
  });

  const addMemberMut = useMutation({
    mutationFn: ({ sam, dn }: { sam: string; dn: string }) => api.addADGroupMember(sam, dn),
    onSuccess: () => { setAddMemberDn(""); setAddMemberError(""); invalidate(); },
    onError: (e: Error) => setAddMemberError(e.message),
  });

  const removeMemberMut = useMutation({
    mutationFn: ({ sam, dn }: { sam: string; dn: string }) => api.removeADGroupMember(sam, dn),
    onSuccess: () => invalidate(),
  });

  const group = groupDetail ?? selected;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="w-72">
          <SearchBar value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search groups…" />
        </div>
        <button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
          + New Group
        </button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-slate-400">Loading…</div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">Type</th>
                <th className="pb-2 pr-4">Email</th>
                <th className="pb-2">Description</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((g) => (
                <tr key={g.dn} onClick={() => setSelected(g)} className="cursor-pointer border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2 pr-4 font-medium text-slate-800">{g.cn}</td>
                  <td className="py-2 pr-4 text-xs text-slate-500">{g.group_type_label}</td>
                  <td className="py-2 pr-4 text-slate-600">{g.email || "—"}</td>
                  <td className="py-2 text-slate-500 truncate max-w-xs">{g.description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && <Pagination page={data.page} total={data.total} limit={data.limit} onChange={setPage} />}
        </>
      )}

      {group && (
        <Panel title={group.cn} open onClose={() => setSelected(null)}>
          <div className="mb-4 flex gap-2">
            <button
              onClick={() => { if (confirm(`Delete group ${group.cn}?`)) deleteMut.mutate(group.sam_account_name); }}
              className="rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700"
            >
              Delete Group
            </button>
          </div>

          <Field label="SAM" value={group.sam_account_name} />
          <Field label="Type" value={group.group_type_label} />
          <Field label="Email" value={group.email} />
          <Field label="Description" value={group.description} />
          <Field label="OU" value={ouLabel(group.dn)} />
          <Field label="Created" value={fmt(group.when_created)} />
          <Field label="Changed" value={fmt(group.when_changed)} />

          <div className="mt-4">
            <p className="mb-2 text-xs font-medium text-slate-500">
              Members ({(group.members ?? []).length})
            </p>
            <div className="mb-3 flex gap-2">
              <input
                className="flex-1 rounded border border-slate-200 px-2 py-1.5 font-mono text-xs"
                placeholder="Distinguished name to add…"
                value={addMemberDn}
                onChange={(e) => setAddMemberDn(e.target.value)}
              />
              <button
                onClick={() => addMemberMut.mutate({ sam: group.sam_account_name, dn: addMemberDn })}
                disabled={!addMemberDn || addMemberMut.isPending}
                className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Add
              </button>
            </div>
            {addMemberError && <p className="mb-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">{addMemberError}</p>}
            <ul className="space-y-1">
              {(group.members ?? []).map((dn) => (
                <li key={dn} className="flex items-center justify-between rounded bg-slate-50 px-2 py-1 text-xs">
                  <span className="truncate text-slate-700">{ouLabel(dn)}</span>
                  <button
                    onClick={() => removeMemberMut.mutate({ sam: group.sam_account_name, dn })}
                    className="ml-2 shrink-0 text-slate-400 hover:text-red-600"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      )}

      {showCreate && (
        <CreateGroupModal
          ous={ous}
          onClose={() => setShowCreate(false)}
          onCreated={(g) => { setShowCreate(false); setSelected(g); invalidate(); }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create group modal
// ---------------------------------------------------------------------------

function CreateGroupModal({ ous, onClose, onCreated }: { ous: ADOU[]; onClose: () => void; onCreated: (g: ADGroup) => void }) {
  const [form, setForm] = useState<CreateADGroupRequest>({
    name: "",
    sam: "",
    ou_dn: ous[0]?.dn ?? "",
    group_type: -2147483646,
    description: "",
    email: "",
  });
  const [error, setError] = useState("");
  const mut = useMutation({ mutationFn: () => api.createADGroup(form), onSuccess: onCreated, onError: (e: Error) => setError(e.message) });

  function f(k: keyof CreateADGroupRequest, v: string | number) {
    setForm((p) => ({ ...p, [k]: v }));
  }

  const GROUP_TYPES = [
    { label: "Global Security", value: -2147483646 },
    { label: "Domain Local Security", value: -2147483644 },
    { label: "Universal Security", value: -2147483640 },
    { label: "Global Distribution", value: 2 },
    { label: "Domain Local Distribution", value: 4 },
    { label: "Universal Distribution", value: 8 },
  ];

  return (
    <Modal title="Create Group" open onClose={onClose}>
      <div className="space-y-3">
        <label className="block text-xs font-medium text-slate-600">
          Group name *
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.name} onChange={(e) => f("name", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Pre-Windows 2000 name (SAM) *
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 font-mono text-sm" value={form.sam} onChange={(e) => f("sam", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          OU *
          <select className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.ou_dn} onChange={(e) => f("ou_dn", e.target.value)}>
            {ous.map((ou) => <option key={ou.dn} value={ou.dn}>{ouLabel(ou.dn)}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Group type
          <select className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.group_type} onChange={(e) => f("group_type", Number(e.target.value))}>
            {GROUP_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Description
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.description ?? ""} onChange={(e) => f("description", e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Email (mail-enabled)
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={form.email ?? ""} onChange={(e) => f("email", e.target.value)} />
        </label>
        {error && <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="rounded border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={() => mut.mutate()} disabled={mut.isPending || !form.name || !form.sam || !form.ou_dn} className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {mut.isPending ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Computers tab
// ---------------------------------------------------------------------------

function ComputersTab() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ADComputer | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["ad-computers", q, page],
    queryFn: () => api.listADComputers({ q, page, limit: 50 }),
  });

  return (
    <div>
      <div className="mb-4 w-72">
        <SearchBar value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search computers…" />
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-slate-400">Loading…</div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">OS</th>
                <th className="pb-2 pr-4">Hostname</th>
                <th className="pb-2 pr-4">Last logon</th>
                <th className="pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((c) => (
                <tr key={c.dn} onClick={() => setSelected(c)} className="cursor-pointer border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2 pr-4 font-medium text-slate-800">{c.cn}</td>
                  <td className="py-2 pr-4 text-slate-600">{c.os || "—"}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-slate-500">{c.dns_hostname || "—"}</td>
                  <td className="py-2 pr-4 text-slate-500">{fmt(c.last_logon)}</td>
                  <td className="py-2">{badge(c.enabled)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && <Pagination page={data.page} total={data.total} limit={data.limit} onChange={setPage} />}
        </>
      )}

      {selected && (
        <Panel title={selected.cn} open onClose={() => setSelected(null)}>
          <Field label="Hostname" value={selected.dns_hostname} />
          <Field label="OS" value={selected.os} />
          <Field label="OS version" value={selected.os_version} />
          <Field label="Description" value={selected.description} />
          <Field label="Managed by" value={selected.managed_by ? ouLabel(selected.managed_by) : "—"} />
          <Field label="Status" value={badge(selected.enabled)} />
          <Field label="Last logon" value={fmt(selected.last_logon)} />
          <Field label="Created" value={fmt(selected.when_created)} />
          <Field label="OU" value={ouLabel(selected.dn)} />
          <Field label="DN" value={<span className="font-mono text-xs break-all">{selected.dn}</span>} />
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OUs tab
// ---------------------------------------------------------------------------

function OUsTab() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data: ous, isLoading } = useQuery({
    queryKey: ["ad-ous"],
    queryFn: () => api.listADOUs(),
  });

  const deleteMut = useMutation({
    mutationFn: (dn: string) => api.deleteADOU(dn),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ad-ous"] }),
  });

  const createMut = useMutation({
    mutationFn: ({ name, parent, desc }: { name: string; parent: string; desc: string }) =>
      api.createADOU(name, parent, desc),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ad-ous"] }); setShowCreate(false); },
  });

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
          + New OU
        </button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-slate-400">Loading…</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
              <th className="pb-2 pr-4">Path</th>
              <th className="pb-2 pr-4">Description</th>
              <th className="pb-2 pr-4">Created</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {(ous ?? []).map((ou) => (
              <tr key={ou.dn} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-medium text-slate-800">{ouLabel(ou.dn)}</td>
                <td className="py-2 pr-4 text-slate-500">{ou.description || "—"}</td>
                <td className="py-2 pr-4 text-slate-500">{fmt(ou.when_created)}</td>
                <td className="py-2">
                  <button
                    onClick={() => { if (confirm(`Delete OU: ${ou.dn}?\nOU must be empty.`)) deleteMut.mutate(ou.dn); }}
                    className="text-xs text-slate-400 hover:text-red-600"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showCreate && (
        <CreateOUModal
          parentDnOptions={ous ?? []}
          onClose={() => setShowCreate(false)}
          onCreate={(name, parent, desc) => createMut.mutate({ name, parent, desc })}
        />
      )}
    </div>
  );
}

function CreateOUModal({
  parentDnOptions,
  onClose,
  onCreate,
}: {
  parentDnOptions: ADOU[];
  onClose: () => void;
  onCreate: (name: string, parent: string, desc: string) => void;
}) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState(parentDnOptions[0]?.dn ?? "");
  const [desc, setDesc] = useState("");
  return (
    <Modal title="Create OU" open onClose={onClose}>
      <div className="space-y-3">
        <label className="block text-xs font-medium text-slate-600">
          OU name *
          <input autoFocus className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Parent container *
          <select className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={parent} onChange={(e) => setParent(e.target.value)}>
            {parentDnOptions.map((ou) => <option key={ou.dn} value={ou.dn}>{ouLabel(ou.dn)}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-slate-600">
          Description
          <input className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm" value={desc} onChange={(e) => setDesc(e.target.value)} />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="rounded border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={() => onCreate(name, parent, desc)} disabled={!name || !parent} className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            Create
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Status banner
// ---------------------------------------------------------------------------

function StatusBanner() {
  const { data } = useQuery({ queryKey: ["ad-status"], queryFn: api.getADStatus, staleTime: 60_000 });
  if (!data) return null;
  if (!data.configured) {
    return (
      <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        Active Directory is not configured. Set <code className="font-mono">AD_SERVER</code>, <code className="font-mono">AD_BASE_DN</code>, <code className="font-mono">AD_BIND_DN</code>, and <code className="font-mono">AD_BIND_PASSWORD</code> in your environment.
      </div>
    );
  }
  if (!data.connected) {
    return (
      <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        Cannot connect to <strong>{data.server}</strong>: {data.error}
      </div>
    );
  }
  return (
    <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
      Connected to <strong>{data.server}</strong> — base DN: <code className="font-mono">{data.base_dn}</code>
      {data.ssl && <span className="ml-2 rounded-full bg-emerald-200 px-1.5 py-0.5 text-xs">SSL</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root page
// ---------------------------------------------------------------------------

export default function ADManagementPage() {
  const [tab, setTab] = useState<Tab>("users");

  const { data: ous = [] } = useQuery({
    queryKey: ["ad-ous"],
    queryFn: () => api.listADOUs(),
    staleTime: 120_000,
  });

  const tabs: { id: Tab; label: string }[] = [
    { id: "users", label: "Users" },
    { id: "groups", label: "Groups" },
    { id: "computers", label: "Computers" },
    { id: "ous", label: "Org Units" },
  ];

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-5">
        <h1 className="text-xl font-semibold text-slate-800">Active Directory</h1>
        <p className="mt-0.5 text-sm text-slate-500">Manage users, groups, computers, and organizational units.</p>
      </div>

      <StatusBanner />

      <div className="mb-5 flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "users" && <UsersTab ous={ous} />}
      {tab === "groups" && <GroupsTab ous={ous} />}
      {tab === "computers" && <ComputersTab />}
      {tab === "ous" && <OUsTab />}
    </div>
  );
}
