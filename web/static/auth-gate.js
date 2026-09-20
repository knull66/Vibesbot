/**
 * Login / register for the Mac lobby. Never send the user to the desk
 * unless the account API actually accepted the credentials.
 */
(function () {
    const form = document.getElementById('auth-form');
    if (!form) return;

    const errorEl = document.getElementById('auth-error');
    const hintEl = document.getElementById('auth-hint');
    const tagEl = document.getElementById('login-tag');
    const inviteGroup = document.getElementById('invite-group');
    const registerTab = document.getElementById('tab-register');
    const submitBtn = document.getElementById('auth-submit');
    const retryBtn = document.getElementById('btn-retry-engine');
    const AUTH_MISSING = 'Old engine still running. Dock → Vibesbot → Quit, then open the app. Cmd+Q does not quit this build.';
    let mode = 'login';
    let status = { setup_required: false, registration_open: false, invite_required: true };
    let ready = false;

    function setEngineDown(on) {
        if (retryBtn) retryBtn.style.display = on ? 'block' : 'none';
        if (submitBtn) submitBtn.disabled = on || !ready;
    }

    function setMode(next) {
        mode = next;
        document.querySelectorAll('.login-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.mode === mode);
        });
        if (inviteGroup) {
            inviteGroup.style.display = (mode === 'register' && status.invite_required && !status.setup_required) ? 'block' : 'none';
        }
        if (submitBtn) {
            submitBtn.textContent = status.setup_required ? 'Create owner' : (mode === 'register' ? 'Create account' : 'Enter');
        }
        if (errorEl && ready) errorEl.textContent = '';
    }

    document.querySelectorAll('.login-tab').forEach(tab => {
        tab.addEventListener('click', () => setMode(tab.dataset.mode));
    });

    function loadStatus() {
        return fetch('/api/auth/status', { credentials: 'same-origin' }).then(r => {
            if (!r.ok) throw new Error('no-auth');
            return r.json();
        }).then(data => {
            status = data;
            ready = true;
            setEngineDown(false);
            if (submitBtn) submitBtn.disabled = false;
            if (errorEl) errorEl.textContent = '';
            if (data.setup_required) {
                if (tagEl) tagEl.textContent = 'Create owner';
                if (hintEl) hintEl.textContent = 'First account becomes the owner. Registration stays invite-only after this.';
                const tabs = document.getElementById('login-tabs');
                if (tabs) tabs.style.display = 'none';
                if (registerTab) registerTab.style.display = 'none';
                setMode('register');
            } else if (!data.registration_open) {
                if (registerTab) registerTab.style.display = 'none';
                const tabs = document.getElementById('login-tabs');
                if (tabs) tabs.style.display = 'none';
                if (hintEl) hintEl.textContent = 'Private desk. Sign in with your account.';
                setMode('login');
            } else {
                if (hintEl) hintEl.textContent = data.invite_required ? 'Register with an invite code from the owner.' : 'Create an account or sign in.';
                setMode('login');
            }
        }).catch(() => {
            ready = false;
            setEngineDown(true);
            if (hintEl) hintEl.textContent = AUTH_MISSING;
            if (errorEl) errorEl.textContent = AUTH_MISSING;
        });
    }

    loadStatus();
    window.setInterval(() => {
        if (!ready) loadStatus();
    }, 2000);
    retryBtn?.addEventListener('click', () => loadStatus());

    window.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && String(e.key).toLowerCase() === 'q') {
            e.preventDefault();
            fetch('/api/system/quit', { method: 'POST', keepalive: true }).catch(() => {});
            window.close();
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (errorEl) errorEl.textContent = '';
        if (!ready) {
            if (errorEl) errorEl.textContent = AUTH_MISSING;
            return;
        }
        if (submitBtn) submitBtn.disabled = true;
        const payload = {
            username: (document.getElementById('username')?.value || '').trim(),
            password: document.getElementById('password')?.value || '',
            invite_code: (document.getElementById('invite')?.value || '').trim()
        };
        const url = mode === 'register' ? '/api/auth/register' : '/api/auth/login';
        try {
            const res = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            let data = {};
            try {
                data = await res.json();
            } catch (err) {
                data = {};
            }
            if (res.status === 404 || res.status === 405) {
                if (errorEl) errorEl.textContent = AUTH_MISSING;
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
            if (!res.ok || !data.success) {
                if (errorEl) errorEl.textContent = data.error || 'Invalid username or password';
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
            window.location.replace('/');
        } catch (err) {
            if (errorEl) errorEl.textContent = AUTH_MISSING;
            if (submitBtn) submitBtn.disabled = false;
        }
    });
})();
