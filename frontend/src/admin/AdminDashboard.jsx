// src/admin/AdminDashboard.jsx
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  adminUsers,
  adminTickets,
  creditUser,
  gradeMatch
} from "../api/betsWallet";

import {
  adminLogin,
  adminListVips,
  adminListPendingVips,
  adminListUpgradeRequests,
  adminApproveVip,
  adminDeclineVip,
  adminApproveUpgrade,
  adminDeclineUpgrade,
  adminPreviewVipPicks,
  adminDistributeVipPicks
} from "../api/authVipAdmin";
export default function AdminDashboard() {
  // --- Auth / Admin ---
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [admin, setAdmin] = useState(() =>
    JSON.parse(localStorage.getItem("admin_user") || "null")
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // --- Data ---
  const [vips, setVips] = useState([]);
  const [pendingVips, setPendingVips] = useState([]);
  const [upgradeRequests, setUpgradeRequests] = useState([]);
  const [allMatches, setAllMatches] = useState([]);
  const [users, setUsers] = useState([]);
  const [tickets, setTickets] = useState([]);

  // --- UI ---
  const [selectedVIPs, setSelectedVIPs] = useState([]);
  const [selectedMatches, setSelectedMatches] = useState([]);
  const [pick, setPick] = useState("1X2");
  const [odds, setOdds] = useState(1.5);
  const [distributionSummary, setDistributionSummary] = useState([]);

  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);

  const [search, setSearch] = useState("");
  const [filterApproved, setFilterApproved] = useState("all");
  const [filterPlan, setFilterPlan] = useState("all");

  // Admin actions
  const [creditAmount, setCreditAmount] = useState("");
  const [selectedUser, setSelectedUser] = useState(null);
  const [gradeMatchId, setGradeMatchId] = useState("");
  const [gradeResult, setGradeResult] = useState("");

  useEffect(() => document.documentElement.classList.add("dark"), []);

  // --- Helpers ---
  const safeArray = (res) => {
    if (!res) return [];
    if (Array.isArray(res)) return res;
    if (Array.isArray(res?.data)) return res.data;
    if (Array.isArray(res?.data?.data)) return res.data.data;
    if (Array.isArray(res?.users)) return res.users;
    if (Array.isArray(res?.tickets)) return res.tickets;
    return [];
  };
  const safeObj = (res) => res?.data ?? res ?? null;

  // --- Auth ---
  const login = async (e) => {
    e?.preventDefault();
    setLoading(true);
    setMsg(null);
    try {
      const res = await adminLogin(username, password);
      const tokenVal = res?.data?.token;
      if (!tokenVal) throw new Error("Invalid login response");

      localStorage.setItem("token", tokenVal);
      localStorage.setItem(
        "admin_user",
        JSON.stringify(res.data.admin || { username })
      );
      setToken(tokenVal);
      setAdmin(res.data.admin || { username });
      setUsername("");
      setPassword("");
    } catch (err) {
      setMsg({ type: "error", text: "Invalid admin credentials" });
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("admin_user");
    setToken(null);
    setAdmin(null);

    // Clear all state
    setVips([]);
    setPendingVips([]);
    setUpgradeRequests([]);
    setAllMatches([]);
    setSelectedVIPs([]);
    setSelectedMatches([]);
    setUsers([]);
    setTickets([]);
    setMsg({ type: "info", text: "Logged out" });
  };

  // --- Fetch all ---
  const fetchAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [
        vipList,
        pendingList,
        upgrades,
        matches,
        usersRes,
        ticketsRes,
      ] = await Promise.all([
        adminListVips(token),
        adminListPendingVips(token),
        adminListUpgradeRequests(token),
        adminPreviewVipPicks(token, 50),
        adminUsers(token),
        adminTickets(token),
      ]);

      setVips(safeArray(vipList));
      setPendingVips(safeArray(pendingList));
      setUpgradeRequests(safeArray(upgrades));
      setAllMatches(safeArray(matches));

      setUsers(safeArray(usersRes));
      setTickets(safeArray(ticketsRes));
    } catch (e) {
      setMsg({ type: "error", text: String(e) });
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [token, fetchAll]);

  // --- VIP actions ---
  const vipAction = async (id, action) => {
    if (!window.confirm(`Are you sure to ${action}?`)) return;
    setLoading(true);
    setMsg(null);
    try {
      if (action === "approve") await adminApproveVip(token, id);
      else if (action === "decline") await adminDeclineVip(token, id);
      await fetchAll();
    } catch (e) {
      setMsg({ type: "error", text: String(e) });
    } finally {
      setLoading(false);
    }
  };
  const upgradeAction = async (reqId, action) => {
    if (!window.confirm(`Are you sure to ${action} this upgrade request?`)) return;
    setLoading(true);
    setMsg(null);
    try {
      if (action === "approve") await adminApproveUpgrade(token, reqId);
      else if (action === "decline") await adminDeclineUpgrade(token, reqId);
      await fetchAll();
    } catch (e) {
      setMsg({ type: "error", text: String(e) });
    } finally {
      setLoading(false);
    }
  };

  // --- Distribution ---
  const distributePicks = async () => {
    if (!selectedVIPs.length || !selectedMatches.length) {
      setMsg({ type: "error", text: "Select at least one VIP and one match" });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const payload = {
        vip_numbers: selectedVIPs,
        matches: selectedMatches.map((m) => ({ match_id: m.match_id, pick, odds })),
      };
      const res = await adminDistributeVipPicks(token, payload);
      const data = safeObj(res);

      if (Array.isArray(data)) setDistributionSummary(data);
      else if (Array.isArray(data?.summary)) setDistributionSummary(data.summary);
      else if (data) setDistributionSummary([data]);
      else setDistributionSummary([]);

      setMsg({ type: "success", text: "Picks distributed successfully" });
      setSelectedVIPs([]);
      setSelectedMatches([]);
    } catch (e) {
      setMsg({ type: "error", text: String(e) });
    } finally {
      setLoading(false);
    }
  };

  // --- Credit User ---
  const creditSelectedUser = async () => {
    if (!selectedUser || !creditAmount) {
      setMsg({ type: "error", text: "Select a user and enter an amount" });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      await creditUser(selectedUser, Number(creditAmount));
      setMsg({ type: "success", text: "User credited successfully" });
      setCreditAmount("");
      setSelectedUser(null);
      await fetchAll();
    } catch (e) {
      setMsg({ type: "error", text: String(e) });
    } finally {
      setLoading(false);
    }
  };

  // --- Grade Match ---
  const gradeMatchResult = async () => {
    if (!gradeMatchId || !gradeResult) {
      setMsg({ type: "error", text: "Provide match id and result" });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      await gradeMatch(gradeMatchId, gradeResult);
      setMsg({ type: "success", text: "Match graded successfully" });
      setGradeMatchId("");
      setGradeResult("");
      await fetchAll();
    } catch (e) {
      setMsg({ type: "error", text: String(e) });
    } finally {
      setLoading(false);
    }
  };

  // --- Filters ---
  const filteredVips = useMemo(() => {
    const q = search.trim().toLowerCase();
    return vips.filter((v) => {
      const matchSearch =
        !q ||
        v.name?.toLowerCase().includes(q) ||
        v.number?.toLowerCase().includes(q) ||
        String(v.id).includes(q);
      const matchApproved =
        filterApproved === "all" ||
        (filterApproved === "yes" && v.approved) ||
        (filterApproved === "no" && !v.approved);
      const matchPlan = filterPlan === "all" || v.subscription === filterPlan;
      return matchSearch && matchApproved && matchPlan;
    });
  }, [vips, search, filterApproved, filterPlan]);

  const toggleVIP = (number, checked) =>
    setSelectedVIPs((prev) => (checked ? [...prev, number] : prev.filter((n) => n !== number)));
  const toggleMatch = (m, checked) =>
    setSelectedMatches((prev) => (checked ? [...prev, m] : prev.filter((x) => x.match_id !== m.match_id)));

  // --- Render login ---
  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100 p-6">
        <form onSubmit={login} className="bg-slate-900 border border-slate-800 p-6 rounded-xl w-full max-w-md space-y-4">
          <h1 className="text-2xl font-bold text-indigo-400 text-center">Admin Login</h1>
          {msg && <Banner msg={msg} />}
          <Input placeholder="Username" value={username} onChange={setUsername} />
          <Input type="password" placeholder="Password" value={password} onChange={setPassword} />
          <Btn className="w-full" disabled={loading}>Login</Btn>
        </form>
      </div>
    );
  }

  // --- Main dashboard UI ---
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex justify-between items-center">
          <h1 className="text-xl font-semibold text-indigo-300">Admin Dashboard</h1>
          <div className="flex items-center gap-3">
            <div className="text-sm text-slate-400">{admin?.username}</div>
            <Btn danger small onClick={logout}>Logout</Btn>
          </div>
        </div>
        {msg && <Banner msg={msg} />}

        {/* VIPs */}
        <Card title="VIP Users">
          <div className="flex gap-2 mb-3">
            <Input placeholder="Search" value={search} onChange={setSearch} />
            <Select value={filterApproved} onChange={setFilterApproved}>
              <option value="all">All</option>
              <option value="yes">Approved</option>
              <option value="no">Not Approved</option>
            </Select>
            <Select value={filterPlan} onChange={setFilterPlan}>
              <option value="all">All Plans</option>
              {[...new Set(vips.map(v => v.subscription).filter(Boolean))].map(plan => (
                <option key={plan} value={plan}>{plan}</option>
              ))}
            </Select>
          </div>
          <Table headers={["ID","Name","Number","Plan","Approved","Expiry","Actions"]}>
            {filteredVips.map(v => (
              <tr key={v.id} className="hover:bg-slate-800">
                <td className="p-2">{v.id}</td>
                <td className="p-2">{v.name}</td>
                <td className="p-2">{v.number}</td>
                <td className="p-2">{v.subscription}</td>
                <td className={`p-2 ${v.approved ? "text-emerald-400" : "text-red-400"}`}>{v.approved ? "YES" : "NO"}</td>
                <td className="p-2">{v.subscription_expiry || "-"}</td>
                <td className="p-2 flex gap-2">
                  {!v.approved && (
                    <>
                      <Btn success small onClick={() => vipAction(v.id, "approve")}>Approve</Btn>
                      <Btn danger small onClick={() => vipAction(v.id, "decline")}>Decline</Btn>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        {/* Pending VIPs */}
        <Card title="Pending VIP Approvals">
          {!pendingVips.length && <div className="text-slate-500">No pending VIPs</div>}
          {pendingVips.map(v => (
            <div key={v.id} className="flex justify-between items-center p-2 hover:bg-slate-800 rounded">
              <span>{v.name} ({v.number})</span>
              <div className="flex gap-2">
                <Btn success small onClick={() => vipAction(v.id, "approve")}>Approve</Btn>
                <Btn danger small onClick={() => vipAction(v.id, "decline")}>Decline</Btn>
              </div>
            </div>
          ))}
        </Card>

        {/* Upgrade Requests */}
        <Card title="VIP Upgrade Requests">
          {!upgradeRequests.length && <div className="text-slate-500">No upgrade requests</div>}
          {upgradeRequests.map(req => (
            <div key={req.id} className="flex justify-between items-center p-2 hover:bg-slate-800 rounded">
              <span>{req.vip_name || req.name} ({req.number}) → {req.plan}</span>
              <div className="flex gap-2">
                <Btn success small onClick={() => upgradeAction(req.id, "approve")}>Approve</Btn>
                <Btn danger small onClick={() => upgradeAction(req.id, "decline")}>Decline</Btn>
              </div>
            </div>
          ))}
        </Card>

        {/* Distribute Picks */}
        <Card title="Distribute Picks to VIPs">
          <div className="grid md:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="text-sm text-slate-400 mb-1 block">Select VIPs</label>
              <div className="bg-slate-950 border border-slate-700 rounded px-3 py-2 w-full h-40 overflow-auto">
                {vips.filter(v => v.approved).map(v => (
                  <label key={v.number} className="flex items-center justify-between p-1 hover:bg-slate-800 rounded cursor-pointer text-sm">
                    <input type="checkbox" className="mr-2" checked={selectedVIPs.includes(v.number)} onChange={e => toggleVIP(v.number, e.target.checked)} />
                    <span>{v.name} ({v.number}) - {v.subscription}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="col-span-2">
              <label className="text-sm text-slate-400 mb-1 block">Select Matches</label>
              <div className="bg-slate-950 border border-slate-700 rounded px-3 py-2 w-full h-40 overflow-auto">
                {allMatches.length === 0 && <div className="text-slate-500 text-sm">No matches available</div>}
                {Object.entries(allMatches.reduce((acc, m) => {
                  const date = m.local ? new Date(m.local).toLocaleDateString() : "Unknown Date";
                  if (!acc[date]) acc[date] = [];
                  acc[date].push(m);
                  return acc;
                }, {})).map(([date, matches]) => (
                  <div key={date} className="mb-2">
                    <div className="text-slate-400 text-xs font-semibold mb-1">{date}</div>
                    {matches.map(m => (
                      <label key={m.match_id} className="flex items-center justify-between p-1 hover:bg-slate-800 rounded cursor-pointer text-sm">
                        <input type="checkbox" className="mr-2" checked={selectedMatches.some(sm => sm.match_id === m.match_id)} onChange={e => toggleMatch(m, e.target.checked)} />
                        <div className="flex flex-col">
                          <span className="font-medium text-indigo-300">{m.home} vs {m.away}</span>
                          {m.local && <span className="text-slate-400 text-xs">{new Date(m.local).toLocaleTimeString()}</span>}
                        </div>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            <Input placeholder="Pick (1X2)" value={pick} onChange={setPick} />
            <Input type="number" placeholder="Odds" value={odds} onChange={setOdds} />
            <Btn className="col-span-full" success onClick={distributePicks} disabled={loading}>Distribute Picks</Btn>
          </div>
        </Card>

        {/* Distribution Summary */}
        <Card title="Distribution Summary">
          {!Array.isArray(distributionSummary) || distributionSummary.length === 0 ? (
            <div className="text-slate-500">No results yet</div>
          ) : (
            distributionSummary.map((s, i) => (
              <div key={i} className="border-b border-slate-800 pb-2 mb-2 text-sm">{JSON.stringify(s)}</div>
            ))
          )}
        </Card>

        {/* Users & Credit */}
        <Card title="Users">
          <Table headers={["ID","Name","Phone","Balance","Credit"]}>
            {users.map(u => (
              <tr key={u.id} className="hover:bg-slate-800">
                <td className="p-2">{u.id}</td>
                <td className="p-2">{u.name}</td>
                <td className="p-2">{u.phone}</td>
                <td className="p-2">{u.balance}</td>
                <td className="p-2">
                  <Input type="number" placeholder="Amount" value={selectedUser === u.id ? creditAmount : ""} onChange={e => { setSelectedUser(u.id); setCreditAmount(e.target.value); }} />
                  <Btn success small onClick={creditSelectedUser}>Credit</Btn>
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        {/* Tickets */}
        <Card title="Tickets">
          <Table headers={["ID","User","Matches","Stake","Status"]}>
            {tickets.map(t => (
              <tr key={t.id} className="hover:bg-slate-800">
                <td className="p-2">{t.id}</td>
                <td className="p-2">{t.user_name}</td>
                <td className="p-2">{t.matches?.map(m => `${m.home} vs ${m.away}`).join(", ")}</td>
                <td className="p-2">{t.stake}</td>
                <td className={`p-2 ${t.status === "won" ? "text-emerald-400" : t.status === "lost" ? "text-red-400" : ""}`}>{t.status}</td>
              </tr>
            ))}
          </Table>
        </Card>

        {/* Grade Match */}
        <Card title="Grade Match">
          <div className="flex gap-2 items-end">
            <Input placeholder="Match ID" value={gradeMatchId} onChange={setGradeMatchId} />
            <Input placeholder="Result" value={gradeResult} onChange={setGradeResult} />
            <Btn success onClick={gradeMatchResult}>Grade Match</Btn>
          </div>
        </Card>

        {loading && <LoadingOverlay />}
      </div>
    </div>
  );
}

/* ---------------- UI components ---------------- */
function Card({ title, children }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      <h2 className="text-indigo-400 font-semibold">{title}</h2>
      {children}
    </div>
  );
}

function Table({ headers, children }) {
  return (
    <table className="table-auto w-full border-collapse border border-slate-800 text-sm">
      <thead>
        <tr>
          {headers.map((h, i) => <th key={i} className="border-b border-slate-800 p-2 text-left">{h}</th>)}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function Input({ type="text", placeholder, value, onChange }) {
  return (
    <input type={type} placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-100 w-full"/>
  );
}

function Select({ value, onChange, children }) {
  return <select value={value} onChange={e => onChange(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-100">{children}</select>;
}

function Btn({ children, success, danger, small, className="", onClick, disabled }) {
  const base = "rounded px-3 py-1 font-semibold text-sm";
  const size = small ? "text-xs py-0.5 px-2" : "";
  const color = success ? "bg-emerald-500 hover:bg-emerald-600 text-black" :
                danger ? "bg-red-500 hover:bg-red-600 text-black" :
                "bg-indigo-500 hover:bg-indigo-600 text-black";
  return <button onClick={onClick} className={`${base} ${size} ${color} ${className}`} disabled={disabled}>{children}</button>;
}

function Banner({ msg }) {
  const color = msg.type === "error" ? "bg-red-600" : msg.type === "success" ? "bg-emerald-600" : "bg-indigo-600";
  return <div className={`${color} p-2 rounded text-black text-sm`}>{msg.text}</div>;
}

function LoadingOverlay() {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="text-indigo-300 font-semibold text-lg">Loading...</div>
    </div>
  );
}
