// Opaque preview frames may request source navigation, never arbitrary URLs/actions.
export function previewCitation(event,frames,documents){
  const d=event.data;
  if(event.origin!=='null'||!d||d.type!=='workbench.citation')return null;
  if(![...frames].some(f=>f.contentWindow===event.source&&f.dataset.artifactPreview===d.artifactId))return null;
  const doc=documents.find(doc=>doc.id===d.docid&&doc.source_hash===d.hash);
  if(!doc||!/^B\d+$/.test(d.block)||!/^B\d+$/.test(d.end))return null;
  const start=Number(d.block.slice(1)),end=Number(d.end.slice(1));
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||end<start||end-start>100000)return null;
  for(let i=start;i<=end;i++)if(!doc.locations?.['B'+i])return null;
  return {docid:d.docid,block:d.block,end:d.end,hash:d.hash};
}
