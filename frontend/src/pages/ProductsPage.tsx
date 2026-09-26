import { useEffect, useState } from "react";
import { api } from "../api/client";
type P = { id: number; name: string; ferment_min: number; bake_min: number };
type Draft = { ferment_min: number; bake_min: number };
export default function ProductsPage() {
  const [rows, setRows] = useState<P[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const reload = () => api<P[]>("/products").then(setRows);
  useEffect(() => { reload(); }, []);
  const draftOf = (p: P): Draft => drafts[p.id] ?? { ferment_min: p.ferment_min, bake_min: p.bake_min };
  const setDraft = (id: number, d: Draft) => setDrafts(prev => ({ ...prev, [id]: d }));
  const clearDraft = (id: number) => setDrafts(prev => { const n = { ...prev }; delete n[id]; return n; });
  async function save(p: P) {
    setMsg(""); setErr("");
    try {
      await api<P>(`/products/${p.id}`, { method: "PUT", body: JSON.stringify(draftOf(p)) });
      clearDraft(p.id);
      setMsg(`已更新「${p.name}」，在排批次与甘特已按新时长重算`);
      reload();
    } catch (e) {
      // 冲突：本次修改不生效，分钟退回改前
      clearDraft(p.id);
      setErr(e instanceof Error ? e.message : String(e));
      reload();
    }
  }
  return (<>
    <h2>产品（配方时长）</h2>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>名称</th><th>发酵 min</th><th>烘烤 min</th><th>合计</th><th></th></tr></thead>
    <tbody>{rows.map(p => {
      const d = draftOf(p);
      const dirty = d.ferment_min !== p.ferment_min || d.bake_min !== p.bake_min;
      return <tr key={p.id}>
        <td>{p.name}</td>
        <td><input className="mono" type="number" min={0} value={d.ferment_min}
          onChange={e => setDraft(p.id, { ...d, ferment_min: Number(e.target.value) })} /></td>
        <td><input className="mono" type="number" min={0} value={d.bake_min}
          onChange={e => setDraft(p.id, { ...d, bake_min: Number(e.target.value) })} /></td>
        <td className="mono">{d.ferment_min + d.bake_min}</td>
        <td><button disabled={!dirty} onClick={() => save(p)}>保存</button></td>
      </tr>;
    })}</tbody></table>
  </>);
}
