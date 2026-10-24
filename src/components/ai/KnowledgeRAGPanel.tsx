"use client";
import { FormEvent, useMemo, useState } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";

type Evidence = { file_id:string; name:string; score:number; excerpt:string; selected:boolean; inclusion_reason:string };
type QueryResult = { answer:string; evidence:Evidence[]; related_files:Array<{file_id:string;name:string;confidence:number;relationship_type:string}>; eligible_file_count:number; generation_note?:string };

export default function KnowledgeRAGPanel() {
  const objects = useSpatialStore((s)=>s.objects);
  const edges = useSpatialStore((s)=>s.edges);
  const selectedIds = useSpatialStore((s)=>s.selectedIds);
  const clearSelection = useSpatialStore((s)=>s.clearSelection);
  const [query,setQuery] = useState("");
  const [includeRelated,setIncludeRelated] = useState(true);
  const [maxRelated,setMaxRelated] = useState(10);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState("");
  const [result,setResult] = useState<QueryResult|null>(null);

  const selectedObjects = useMemo(()=>selectedIds.map((id)=>objects.find((o)=>o.id===id)).filter(Boolean),[selectedIds,objects]);
  const relatedPreview = useMemo(()=>{
    if(!includeRelated||!selectedIds.length)return [];
    const selected=new Set(selectedIds);
    const candidates=new Map<string,{id:string;confidence:number;type:string}>();
    for(const edge of edges){
      const confidence=Number(edge.confidence??0);
      if(confidence<0.75)continue;
      const id=selected.has(edge.source)&&!selected.has(edge.target)?edge.target:selected.has(edge.target)&&!selected.has(edge.source)?edge.source:null;
      if(!id)continue;
      const previous=candidates.get(id);
      if(!previous||confidence>previous.confidence)candidates.set(id,{id,confidence,type:edge.type});
    }
    return [...candidates.values()].sort((a,b)=>b.confidence-a.confidence||a.id.localeCompare(b.id)).slice(0,maxRelated)
      .map((item)=>({...item,name:objects.find((o)=>o.id===item.id)?.name??item.id.slice(0,10)}));
  },[edges,includeRelated,maxRelated,objects,selectedIds]);

  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const text=query.trim();
    if(!text||loading)return;
    if(!selectedIds.length){setError("Select at least one file node in the graph before asking a scoped question.");return;}
    setLoading(true);setError("");setResult(null);
    try{
      const response=await api.queryKnowledge({query:text,selected_file_ids:selectedIds,include_related:includeRelated,max_related_files:maxRelated,min_confidence:0.75});
      setResult(response as QueryResult);
    }catch(err){setError(err instanceof Error?err.message:"The scoped retrieval request failed.");}
    finally{setLoading(false);}
  }

  return <section className="knowledge-rag-panel" aria-label="Knowledge graph query workspace">
    <div className="knowledge-rag-header">
      <div className="knowledge-rag-heading">
        <span className="knowledge-rag-kicker">KNOWLEDGE WORKSPACE</span><strong>Ask your graph</strong>
        <span className="knowledge-rag-muted">{selectedIds.length} selected · {includeRelated?relatedPreview.length+" related in preview":"related files off"}</span>
      </div>
      <div className="knowledge-rag-policy">
        <label className="knowledge-rag-toggle"><input type="checkbox" checked={includeRelated} onChange={(e)=>setIncludeRelated(e.target.checked)}/><span>Include related</span></label>
        <label className="knowledge-rag-limit"><span>Max related</span><select value={maxRelated} onChange={(e)=>setMaxRelated(Number(e.target.value))} disabled={!includeRelated}><option value={0}>0</option><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option><option value={50}>50</option></select></label>
        {!!selectedIds.length&&<button type="button" className="knowledge-rag-text-button" onClick={clearSelection}>Clear selection</button>}
      </div>
    </div>
    <div className="knowledge-rag-scope" aria-label="Retrieval scope preview">
      {!selectedObjects.length?<span className="knowledge-rag-empty-scope">Select graph nodes to define the retrieval scope.</span>:<>
        {selectedObjects.map((o)=>o&&<span className="knowledge-rag-chip knowledge-rag-chip-selected" key={o.id} title={o.id}><span className="knowledge-rag-chip-dot"/>{o.name}<small>selected</small></span>)}
        {relatedPreview.map((item)=><span className="knowledge-rag-chip knowledge-rag-chip-related" key={item.id} title={item.type+" · "+Math.round(item.confidence*100)+"%"}><span className="knowledge-rag-chip-dot"/>{item.name}<small>{Math.round(item.confidence*100)}%</small></span>)}
      </>}
    </div>
    <form className="knowledge-rag-form" onSubmit={submit}>
      <div className="knowledge-rag-input-wrap"><span className="knowledge-rag-input-icon" aria-hidden="true">⌕</span><input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder={selectedIds.length?"Ask a question about the selected files…":"Select one or more files in the graph first"} aria-label="Ask a question about selected files" disabled={loading}/><span className="knowledge-rag-shortcut">Enter ↵</span></div>
      <button className="knowledge-rag-submit" type="submit" disabled={loading||!query.trim()||!selectedIds.length}>{loading?<><span className="knowledge-rag-spinner"/>Searching</>:<>Retrieve evidence <span aria-hidden="true">↗</span></>}</button>
    </form>
    {(error||result)&&<div className="knowledge-rag-results" aria-live="polite">
      {error&&<div className="knowledge-rag-error" role="alert">{error}</div>}
      {result&&<>
        <div className="knowledge-rag-result-summary"><div><span className="knowledge-rag-result-label">RETRIEVAL RESULT</span><p>{result.answer}</p></div><div className="knowledge-rag-result-count"><strong>{result.evidence.length}</strong><span>passages</span></div></div>
        {result.generation_note&&<p className="knowledge-rag-generation-note">{result.generation_note}</p>}
        {result.evidence.length?<div className="knowledge-rag-evidence-list">{result.evidence.map((item)=><article className="knowledge-rag-evidence" key={item.file_id+"-"+item.inclusion_reason}>
          <div className="knowledge-rag-evidence-heading"><strong>{item.name}</strong><span className={item.selected?"knowledge-rag-badge-selected":"knowledge-rag-badge-related"}>{item.selected?"Selected":"Related"}</span><span className="knowledge-rag-score">{Math.round(item.score*100)}% match</span></div>
          <p>{item.excerpt}</p><small>{item.inclusion_reason} · ID {item.file_id}</small>
        </article>)}</div>:<div className="knowledge-rag-no-evidence">No matching excerpts were found in the eligible scope.</div>}
      </>}
    </div>}
    {!result&&!error&&<div className="knowledge-rag-footnote">Evidence is searched only inside selected files and the bounded related-file set.</div>}
  </section>;
}
