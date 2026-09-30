// A stand-in for supabase-js, for recording the demo: sign-in, the database and sessions are faked in the page.
(function () {
  const USER = {
    id: '00000000-0000-4000-8000-000000000001',
    email: 'alex.demo@example.com',
    email_confirmed_at: new Date().toISOString(),
    last_sign_in_at: new Date().toISOString(),
  };
  const signedIn = () => { try { return localStorage.getItem('demo_signed_in') === '1'; } catch (e) { return false; } };
  const session = () => (signedIn() ? { access_token: 'demo-token', user: USER } : null);
  const wait = ms => new Promise(r => setTimeout(r, ms));

  const db = { match_profiles: null };

  function query(table) {
    const q = { table, op: 'select', single: false, maybe: false, payload: null };
    const run = async () => {
      await wait(120);
      if (table === 'match_profiles') {
        if (q.op === 'insert' || q.op === 'upsert') db.match_profiles = Object.assign({}, q.payload);
        else if (q.op === 'update') db.match_profiles = Object.assign({}, db.match_profiles || {}, q.payload);
        else if (q.op === 'delete') db.match_profiles = null;
        const row = db.match_profiles;
        return { data: q.single || q.maybe ? row : (row ? [row] : []), error: null };
      }
      if (q.op === 'select') return { data: q.single || q.maybe ? null : [], error: null };
      return { data: null, error: null };
    };
    const chain = new Proxy(q, {
      get(target, prop) {
        if (prop === 'then') return (res, rej) => run().then(res, rej);
        if (prop === 'insert' || prop === 'update' || prop === 'upsert') return p => { if (target.op === 'select') target.op = prop; target.payload = p; return chain; };
        if (prop === 'delete') return () => { target.op = 'delete'; return chain; };
        if (prop === 'single') return () => { target.single = true; return chain; };
        if (prop === 'maybeSingle') return () => { target.maybe = true; return chain; };
        return () => chain;   // select, eq, order, in, limit…
      },
    });
    return chain;
  }

  window.supabase = {
    createClient() {
      return {
        auth: {
          getSession: async () => ({ data: { session: session() }, error: null }),
          getUser: async () => ({ data: { user: signedIn() ? USER : null }, error: null }),
          onAuthStateChange(cb) {
            setTimeout(() => cb('INITIAL_SESSION', session()), 0);
            return { data: { subscription: { unsubscribe() {} } } };
          },
          signInWithOtp: async () => { await wait(700); return { error: null }; },
          signOut: async () => { try { localStorage.removeItem('demo_signed_in'); } catch (e) {} return { error: null }; },
        },
        from: query,
        rpc: async () => ({ data: null, error: null }),
      };
    },
  };
})();
