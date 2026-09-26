import { useEffect, useState } from "react";
import { api } from "../api/client";

type P = { id: number; name: string; ferment_min: number; bake_min: number };
type Draft = { ferment: number; bake: number };
type UpdateResult = { product: P; rescheduled: number };

function errText(e: unknown): string {
  const s = e instanceof Error ? e.message : String(e);
  try {
    const j = JSON.parse(s) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch { /* 非 JSON 错误体，原样展示 */ }
  return s;
}

export default function ProductsPage() {
  const [rows, setRows] = useState<P[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api<P[]>("/products").then((ps) => {
      setRows(ps);
      setDrafts(Object.fromEntries(
        ps.map((p): [number, Draft] => [p.id, { ferment: p.ferment_min, bake: p.bake_min }]),
      ));
    });
  }, []);

  function setDraft(id: number, patch: Partial<Draft>) {
    setDrafts((ds) => ({ ...ds, [id]: { ...ds[id], ...patch } }));
  }

  async function save(p: P) {
    setMsg(""); setErr("");
    const d = drafts[p.id];
    try {
      const r = await api<UpdateResult>(`/products/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ferment_min: d.ferment, bake_min: d.bake }),
      });
      setRows((rs) => rs.map((x) => (x.id === p.id ? r.product : x)));
      setMsg(`已保存 ${r.product.name}：${r.rescheduled} 个在排批次按新时长重算，批次与甘特已同步`);
    } catch (e) {
      // 与同炉其他批次重叠：本次修改不生效，分钟退回改前
      setDrafts((ds) => ({ ...ds, [p.id]: { ferment: p.ferment_min, bake: p.bake_min } }));
      setErr(errText(e));
    }
  }

  return (<>
    <h2>产品（配方时长）</h2>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>名称</th><th>发酵 min</th><th>烘烤 min</th><th>合计</th><th></th></tr></thead>
    <tbody>{rows.map(p => {
      const d = drafts[p.id] ?? { ferment: p.ferment_min, bake: p.bake_min };
      const dirty = d.ferment !== p.ferment_min || d.bake !== p.bake_min;
      return <tr key={p.id}>
        <td>{p.name}</td>
        <td><input className="mono" type="number" min={0} style={{ width: 70 }} value={d.ferment}
          onChange={(e) => setDraft(p.id, { ferment: Number(e.target.value) })} /></td>
        <td><input className="mono" type="number" min={0} style={{ width: 70 }} value={d.bake}
          onChange={(e) => setDraft(p.id, { bake: Number(e.target.value) })} /></td>
        <td className="mono">{d.ferment + d.bake}</td>
        <td><button disabled={!dirty} onClick={() => save(p)}>保存并重算</button></td>
      </tr>;
    })}</tbody></table>
    <p style={{ color: "var(--bake-muted)", fontSize: ".8rem" }}>
      保存后所有在排批次按新时长重算发酵/烘烤两段；若与同炉其他批次重叠，修改不生效，分钟退回改前。
    </p>
  </>);
}
