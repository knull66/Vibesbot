/**
 * Vibesbot Service Worker
 * Enables PWA functionality: caching, offline support
 */

const CACHE_NAME = 'vibesbot-v1.27.0';
const STATIC_ASSETS = [
    '/',
    '/static/styles.css',
    '/static/app.js',
    '/static/manifest.json',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png'
];

// Install - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate - clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME)
                        .map((name) => {
                            console.log('[SW] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch - network first, fallback to cache
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    
    // Skip WebSocket and API requests
    if (url.pathname.startsWith('/ws') || url.pathname.startsWith('/api/')) {
        return;
    }
    
    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Clone and cache successful responses
                if (response.ok) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME)
                        .then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                }
                return response;
            })
            .catch(() => {
                // Fallback to cache
                return caches.match(event.request)
                    .then((cachedResponse) => {
                        if (cachedResponse) {
                            return cachedResponse;
                        }
                        
                        // Return offline page for navigation requests
                        if (event.request.mode === 'navigate') {
                            return caches.match('/');
                        }
                        
                        return new Response('Offline', {
                            status: 503,
                            statusText: 'Service Unavailable'
                        });
                    });
            })
    );
});

// Background sync for when coming back online
self.addEventListener('sync', (event) => {
    console.log('[SW] Background sync:', event.tag);
});

// Push notifications (for future use)
self.addEventListener('push', (event) => {
    if (event.data) {
        const data = event.data.json();
        
        const options = {
            body: data.body || 'New notification',
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/icon-72.png',
            vibrate: [100, 50, 100],
            data: data.url || '/',
            actions: [
                { action: 'open', title: 'Open' },
                { action: 'close', title: 'Close' }
            ]
        };
        
        event.waitUntil(
            self.registration.showNotification(data.title || 'Vibesbot', options)
        );
    }
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    
    if (event.action === 'open' || !event.action) {
        event.waitUntil(
            clients.openWindow(event.notification.data || '/')
        );
    }
});
