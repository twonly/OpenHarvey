// Apply user JSON after SDK serialization, identically for both wire protocols.
export default async function requestParams() {
  return {config: async config => {
    for (const provider of Object.values(config.provider || {})) {
      const options=provider.options;
      if (!options?.workbenchExtraBody || !Object.keys(options.workbenchExtraBody).length) continue;
      const extra=options.workbenchExtraBody, original=options.fetch || globalThis.fetch;
      options.fetch=async (url,init) => {
        if (init?.method?.toUpperCase()==='POST' && typeof init.body==='string') {
          const body=JSON.parse(init.body);
          if (Array.isArray(body.messages)) init={...init,body:JSON.stringify({...body,...extra})};
        }
        return original(url,init);
      };
    }
  }};
}
