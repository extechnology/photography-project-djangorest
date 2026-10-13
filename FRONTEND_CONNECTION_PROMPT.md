# ⚡ FRONTEND CONNECTION & INTEGRATION SPECIFICATION: EX SHARE ATELIER SUBDOMAINS

> **Target Role**: Senior Frontend / Full-Stack Engineer / AI Coding Agent  
> **Framework**: React / Next.js / Vite / Vue / Nuxt, TypeScript, Tailwind CSS, Axios or Fetch  
> **Production API Base URL**: `https://server.exshare.ai` (or `/api` via reverse proxy)  
> **Root Domain**: `exshare.ai`  
> **DNS Provider**: BigRock (LogicBoxes HTTP API)

---

## 📌 Executive Architecture & Ingress Routing

The frontend must serve two distinct user flows:
1. **Main Studio App (`app.exshare.ai` or `localhost:3000`)**: Authenticated photographers managing their account, galleries, and portfolio custom subdomain under Studio Settings (`PortfolioSubdomainSettings.tsx`).
2. **Public Tenant Showcase (`<subdomain>.exshare.ai` or `<subdomain>.localhost:3000`)**: Public visitors viewing a photographer's published portfolio, browsing photo works, submitting inquiries, and sending analytics (`TenantPortfolioSite.tsx`).

### Ingress & Subdomain Detection Strategy

```typescript
// src/utils/tenant.ts
export const getTenantSubdomain = (): string | null => {
  if (typeof window === 'undefined') return null;

  const hostname = window.location.hostname.toLowerCase();

  // Local development fallback: check URL query param ?subdomain=mridhul or localStorage
  const urlParams = new URLSearchParams(window.location.search);
  const debugSub = urlParams.get('subdomain');
  if (debugSub) return debugSub.toLowerCase();

  // Central / Main App Domains (Not photographer subdomains)
  const mainDomains = [
    'exshare.ai',
    'www.exshare.ai',
    'app.exshare.ai',
    'server.exshare.ai',
    'localhost',
    '127.0.0.1'
  ];
  if (mainDomains.includes(hostname)) return null;

  // Handle *.localhost (e.g. mridhul.localhost in local development)
  if (hostname.endsWith('.localhost')) {
    const sub = hostname.replace('.localhost', '');
    return sub && !sub.includes('.') ? sub : null;
  }

  // Handle *.exshare.ai (e.g. mridhul.exshare.ai in production)
  if (hostname.endsWith('.exshare.ai')) {
    const parts = hostname.split('.');
    // Exactly 3 parts: [<subdomain>, 'exshare', 'ai']
    if (parts.length === 3) {
      const sub = parts[0];
      const reserved = ['www', 'app', 'api', 'admin', 'auth', 'server', 'static', 'media'];
      return reserved.includes(sub) ? null : sub;
    }
  }

  return null;
};
```

---

## 🔌 API Endpoints Contract

All endpoints are hosted under `/api/`:

| Method | Endpoint | Access | Purpose | Payload | Response |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/portfolio/subdomain/availability/?name=<name>` | Authenticated | Check real-time subdomain availability | None | **200 OK**: `{"name":"mridhul", "available":true, "reason":null, "is_current_owner":false}` |
| `PUT` | `/api/portfolio/subdomain/` | Authenticated Owner | Atomically claim subdomain & trigger BigRock DNS creation | `{"subdomain":"mridhul"}` | **202 Accepted**: `{"status":"pending", "subdomain":"mridhul", "domain":"mridhul.exshare.ai", "url":"https://mridhul.exshare.ai"}` |
| `GET` | `/api/portfolio/subdomain/status/` | Authenticated Owner | Check DNS provisioning health & status | None | **200 OK**: `{"subdomain":"mridhul", "status":"active", "domain":"mridhul.exshare.ai", "url":"https://mridhul.exshare.ai", "error":null, "retry_allowed":false}` |
| `POST` | `/api/portfolio/subdomain/retry/` | Authenticated Owner | Retry failed BigRock DNS provisioning (throttled) | None | **202 Accepted**: `{"status":"pending", "subdomain":"mridhul", "message":"DNS provisioning retry scheduled."}` |
| `GET` | `/api/public/portfolio-site/` | Public Visitor | Retrieve published portfolio resolved from `Host` | None | **200 OK**: Serialized `PortfolioConfig` with featured works & photos (or **404** if not found / draft) |
| `POST` | `/api/public/portfolio-site/inquiries/` | Public Visitor | Submit client booking inquiry bound to tenant | `{"client_name":"...", "client_email":"...", "message":"..."}` | **200 OK**: `{"success":true, "inquiry_id": 42}` |
| `POST` | `/api/public/portfolio-site/track-view/` | Public Visitor | Record telemetry / view metrics | `{"page_section":"hero", "device":"desktop"}` | **200 OK**: `{"success":true, "tracked":true}` |

### Detailed Status Code Responses:

#### Availability Reasons (`available: false`):
- `"already_taken"`: Subdomain is owned by another photographer.
- `"reserved"`: Platform reserved keyword (`www`, `api`, `admin`, `app`, etc.).
- `"invalid_format"`: Violates RFC 1035 (length < 3 or > 63, leading/trailing hyphen, contains dots, spaces, underscores, URLs).

#### Claim Responses:
- `HTTP 202 Accepted`: Subdomain atomically claimed; BigRock background worker enqueued.
- `HTTP 409 Conflict`: `{"error": "Subdomain already claimed.", "code": "SUBDOMAIN_ALREADY_TAKEN"}`
- `HTTP 400 Bad Request`: `{"error": "Subdomain renaming is not permitted.", "code": "RENAME_PROHIBITED"}`

#### Retry Provisioning:
- `HTTP 202 Accepted`: Retry task dispatched.
- `HTTP 429 Too Many Requests`: `{"error": "Please wait before retrying.", "code": "RETRY_THROTTLED", "retry_after_seconds": 26}`

---

## 🛠️ API Client Setup (Axios / Fetch)

```typescript
// src/api/client.ts
import axios from 'axios';
import { getTenantSubdomain } from '../utils/tenant';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'https://server.exshare.ai';

// 1. Authenticated Studio Client
export const authApi = axios.create({
  baseURL: BACKEND_URL,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
});

authApi.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  if (token) {
    config.headers.Authorization = token.startsWith('Bearer ') || token.startsWith('Token ')
      ? token
      : `Bearer ${token}`;
  }
  return config;
});

// 2. Anonymous Public Portfolio Client
export const publicTenantApi = axios.create({
  baseURL: BACKEND_URL,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
});

publicTenantApi.interceptors.request.use((config) => {
  const tenant = getTenantSubdomain();
  if (tenant) {
    config.headers['X-Tenant-Subdomain'] = tenant;
  }
  return config;
});
```

---

## 📦 TypeScript Interfaces & Data Contracts

```typescript
// src/types/portfolio.ts

export type SubdomainStatus = 'pending' | 'provisioning' | 'active' | 'failed' | null;

export interface SubdomainAvailability {
  name: string;
  available: boolean;
  reason: 'already_taken' | 'reserved' | 'invalid_format' | null;
  is_current_owner: boolean;
  domain?: string;
  url?: string;
}

export interface SubdomainStatusResponse {
  subdomain: string | null;
  status: SubdomainStatus;
  domain: string | null;
  url: string | null;
  error: string | null;
  retry_allowed: boolean;
}

export interface FeaturedWork {
  id: string;
  title: string;
  category: string;
  coverUrl: string;
  year?: string;
  location?: string;
  mediaCount: number;
  highlightMedia: string[];
}

export interface TenantPortfolioData {
  templateId: string;
  studioName: string;
  artistName: string;
  tagline?: string;
  bio?: string;
  aboutStory?: string;
  location?: string;
  avatarUrl?: string;
  bannerUrl?: string;
  contactEmail?: string;
  contactPhone?: string;
  instagramHandle?: string;
  youtubeHandle?: string;
  websiteUrl?: string;
  isBookingOpen: boolean;
  pricingStartingAt?: string;
  accentColor?: string;
  subdomain: string;
  featuredWorks: FeaturedWork[];
  
  // WhatsApp Integration
  whatsappEnabled?: boolean;
  whatsappNumber?: string;
  whatsappPrefillMessage?: string;
  cleanWhatsappNumber?: string;
}

export interface ClientInquiryPayload {
  client_name: string;
  client_email: string;
  client_phone?: string;
  event_type?: string;
  event_date?: string;
  location?: string;
  budget?: string;
  message: string;
}
```

---

## 🎣 Custom Hook: `useSubdomainSettings`

```typescript
// src/hooks/useSubdomainSettings.ts
import { useState, useEffect, useRef, useCallback } from 'react';
import { authApi } from '../api/client';
import { SubdomainAvailability, SubdomainStatusResponse } from '../types/portfolio';

export const useSubdomainSettings = () => {
  const [subdomainInput, setSubdomainInput] = useState('');
  const [statusData, setStatusData] = useState<SubdomainStatusResponse | null>(null);
  const [availability, setAvailability] = useState<SubdomainAvailability | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [retryCooldown, setRetryCooldown] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 1. Fetch current status
  const refreshStatus = useCallback(async () => {
    try {
      const res = await authApi.get<SubdomainStatusResponse>('/api/portfolio/subdomain/status/');
      setStatusData(res.data);
      if (res.data.subdomain && !subdomainInput) {
        setSubdomainInput(res.data.subdomain);
      }
    } catch (err) {
      console.error('Failed to load subdomain status', err);
    }
  }, [subdomainInput]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // 2. Poll every 4 seconds when provisioning is pending
  useEffect(() => {
    if (statusData?.status === 'pending' || statusData?.status === 'provisioning') {
      const interval = setInterval(refreshStatus, 4000);
      return () => clearInterval(interval);
    }
  }, [statusData?.status, refreshStatus]);

  // 3. Countdown timer for retry rate limit
  useEffect(() => {
    if (retryCooldown <= 0) return;
    const timer = setInterval(() => setRetryCooldown((c) => c - 1), 1000);
    return () => clearInterval(timer);
  }, [retryCooldown]);

  // 4. Debounced availability check (400ms) with AbortController
  const onInputChange = (val: string) => {
    const clean = val.toLowerCase().replace(/[^a-z0-9-]/g, '');
    setSubdomainInput(clean);
    setErrorMessage(null);

    if (abortControllerRef.current) abortControllerRef.current.abort();
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);

    if (!clean || clean.length < 3) {
      setAvailability(null);
      setIsChecking(false);
      return;
    }

    setIsChecking(true);
    debounceTimerRef.current = setTimeout(async () => {
      abortControllerRef.current = new AbortController();
      try {
        const res = await authApi.get<SubdomainAvailability>(
          `/api/portfolio/subdomain/availability/?name=${encodeURIComponent(clean)}`,
          { signal: abortControllerRef.current.signal }
        );
        setAvailability(res.data);
      } catch (err: any) {
        if (err.name !== 'CanceledError') {
          console.error(err);
        }
      } finally {
        setIsChecking(false);
      }
    }, 400);
  };

  // 5. Claim submission
  const claimSubdomain = async () => {
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await authApi.put('/api/portfolio/subdomain/', { subdomain: subdomainInput });
      await refreshStatus();
    } catch (err: any) {
      if (err.response?.status === 409) {
        setErrorMessage('This subdomain was just claimed by another studio.');
      } else if (err.response?.status === 400) {
        setErrorMessage(err.response.data?.error || 'Subdomain renaming is not permitted.');
      } else {
        setErrorMessage('Failed to reserve subdomain. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // 6. Retry provisioning
  const retryProvisioning = async () => {
    if (retryCooldown > 0) return;
    setIsRetrying(true);
    setErrorMessage(null);
    try {
      await authApi.post('/api/portfolio/subdomain/retry/');
      await refreshStatus();
    } catch (err: any) {
      if (err.response?.status === 429) {
        const wait = err.response.data?.retry_after_seconds || 30;
        setRetryCooldown(wait);
        setErrorMessage(`Please wait ${wait}s before retrying.`);
      } else {
        setErrorMessage('Failed to trigger retry.');
      }
    } finally {
      setIsRetrying(false);
    }
  };

  return {
    subdomainInput,
    statusData,
    availability,
    isChecking,
    isSubmitting,
    isRetrying,
    retryCooldown,
    errorMessage,
    onInputChange,
    claimSubdomain,
    retryProvisioning,
    refreshStatus,
  };
};
```

---

## 🎨 UI Components Implementation

### 1. Studio Dashboard Settings Component (`PortfolioSubdomainSettings.tsx`)

```tsx
import React, { useState } from 'react';
import { useSubdomainSettings } from '../hooks/useSubdomainSettings';

export const PortfolioSubdomainSettings: React.FC = () => {
  const {
    subdomainInput,
    statusData,
    availability,
    isChecking,
    isSubmitting,
    isRetrying,
    retryCooldown,
    errorMessage,
    onInputChange,
    claimSubdomain,
    retryProvisioning,
  } = useSubdomainSettings();

  const [copied, setCopied] = useState(false);

  const isFormDisabled =
    isSubmitting ||
    statusData?.status === 'pending' ||
    statusData?.status === 'provisioning';

  const previewUrl = subdomainInput
    ? `https://${subdomainInput}.exshare.ai`
    : 'https://yourstudio.exshare.ai';

  const copyUrl = (url: string) => {
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="max-w-2xl bg-neutral-900 border border-neutral-800 rounded-2xl p-6 sm:p-8 text-neutral-100 shadow-xl">
      <div className="flex items-center justify-between pb-5 border-b border-neutral-800">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <span>Portfolio Custom Subdomain</span>
            {statusData?.status === 'active' && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                Live & Active
              </span>
            )}
          </h2>
          <p className="text-sm text-neutral-400 mt-1">
            Connect an exclusive branded handle for your atelier showcase.
          </p>
        </div>
      </div>

      <div className="mt-6 space-y-6">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-2">
            Subdomain Handle
          </label>
          <div className="flex rounded-xl bg-neutral-950 border border-neutral-800 focus-within:border-amber-500 overflow-hidden transition-colors">
            <input
              type="text"
              value={subdomainInput}
              onChange={(e) => onInputChange(e.target.value)}
              disabled={isFormDisabled}
              placeholder="e.g. mridhul"
              className="flex-1 bg-transparent px-4 py-3 text-white font-mono outline-none disabled:opacity-50"
              maxLength={63}
            />
            <span className="px-4 py-3 bg-neutral-900 text-neutral-400 font-mono text-sm border-l border-neutral-800 select-none">
              .exshare.ai
            </span>
          </div>

          {/* Validation Feedback */}
          <div className="mt-2 text-xs min-h-[20px]">
            {isChecking && <span className="text-amber-400 animate-pulse">Checking availability...</span>}
            {!isChecking && availability && (
              availability.available ? (
                <span className="text-emerald-400 font-medium">✓ Subdomain is available!</span>
              ) : (
                <span className="text-rose-400 font-medium">✗ Unavailable ({availability.reason})</span>
              )
            )}
          </div>
        </div>

        {/* URL Preview Card */}
        <div className="p-4 rounded-xl bg-neutral-950 border border-neutral-800 flex items-center justify-between">
          <div className="truncate">
            <div className="text-xs text-neutral-500">Live Web Address</div>
            <div className="text-sm font-mono text-neutral-200 truncate">{previewUrl}</div>
          </div>
          {statusData?.status === 'active' && statusData.url && (
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => copyUrl(statusData.url!)}
                className="px-3 py-1.5 rounded-lg bg-neutral-800 text-xs text-neutral-200 hover:bg-neutral-700 transition"
              >
                {copied ? 'Copied! ✓' : 'Copy Link'}
              </button>
              <a
                href={statusData.url}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/30 text-xs font-semibold hover:bg-amber-500/20 transition"
              >
                Visit Site ↗
              </a>
            </div>
          )}
        </div>

        {/* BigRock Provisioning Status Banners */}
        {(statusData?.status === 'pending' || statusData?.status === 'provisioning') && (
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 flex items-center gap-3">
            <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin shrink-0" />
            <div className="text-xs">
              <p className="font-semibold text-amber-300">DNS Provisioning in Progress...</p>
              <p className="text-amber-200/80 mt-0.5">
                Configuring DNS A-records on BigRock. This usually completes in 1–2 minutes.
              </p>
            </div>
          </div>
        )}

        {statusData?.status === 'failed' && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-200 flex items-center justify-between gap-3">
            <div className="text-xs">
              <p className="font-semibold text-rose-300">Provisioning Failed</p>
              <p className="text-rose-200/80 mt-0.5">
                {statusData.error || errorMessage || 'An unexpected DNS conflict occurred.'}
              </p>
            </div>
            <button
              type="button"
              onClick={retryProvisioning}
              disabled={isRetrying || retryCooldown > 0}
              className="px-3 py-1.5 bg-rose-500 text-white text-xs font-semibold rounded-lg hover:bg-rose-600 disabled:opacity-50"
            >
              {retryCooldown > 0 ? `Wait ${retryCooldown}s` : isRetrying ? 'Retrying...' : 'Retry Now'}
            </button>
          </div>
        )}

        {errorMessage && statusData?.status !== 'failed' && (
          <div className="p-3 bg-rose-950/60 border border-rose-800 text-rose-300 text-xs rounded-xl">
            {errorMessage}
          </div>
        )}

        <div className="flex justify-end pt-4 border-t border-neutral-800">
          <button
            type="button"
            onClick={claimSubdomain}
            disabled={
              isFormDisabled ||
              !subdomainInput ||
              availability?.available === false ||
              statusData?.status === 'active'
            }
            className="px-6 py-2.5 bg-amber-500 hover:bg-amber-400 text-neutral-950 font-semibold rounded-xl text-sm transition disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed"
          >
            {isSubmitting ? 'Reserving...' : 'Save & Connect Subdomain'}
          </button>
        </div>
      </div>
    </div>
  );
};
```

---

### 2. Public Showcase Page (`TenantPortfolioSite.tsx`)

```tsx
import React, { useEffect, useState } from 'react';
import { publicTenantService } from '../api/subdomainService';
import { TenantPortfolioData } from '../types/portfolio';

export const TenantPortfolioSite: React.FC = () => {
  const [data, setData] = useState<TenantPortfolioData | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    // 1. Fetch showcase configuration bound to the Host header
    publicTenantService
      .getPortfolioShowcase()
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setNotFound(true);
        }
        setLoading(false);
      });

    // 2. Fire telemetry page view tracker
    publicTenantService.trackView({ page_section: 'hero', device: 'desktop' }).catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center text-neutral-400 font-mono text-sm">
        Loading portfolio atelier...
      </div>
    );
  }

  if (notFound || !data) {
    return (
      <div className="min-h-screen bg-black flex flex-col items-center justify-center text-center p-6 text-neutral-100">
        <h1 className="text-3xl font-serif mb-2">Showcase Not Found</h1>
        <p className="text-neutral-500 text-sm max-w-md">
          This photography showcase is either currently unpublished or the custom domain is pending DNS configuration.
        </p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-neutral-100 selection:bg-amber-500 selection:text-black">
      {/* Hero Header */}
      <header className="relative pt-24 pb-16 px-6 max-w-6xl mx-auto text-center">
        {data.avatarUrl && (
          <img
            src={data.avatarUrl}
            alt={data.studioName}
            className="w-24 h-24 rounded-full mx-auto mb-6 object-cover border-2 border-neutral-800 shadow-2xl"
          />
        )}
        <h1 className="text-4xl sm:text-5xl font-serif tracking-tight text-white mb-3">
          {data.studioName}
        </h1>
        {data.tagline && (
          <p className="text-neutral-400 text-base max-w-2xl mx-auto font-light leading-relaxed">
            {data.tagline}
          </p>
        )}
      </header>

      {/* Featured Works Grid */}
      <section className="max-w-6xl mx-auto px-6 py-12">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {data.featuredWorks.map((work) => (
            <div key={work.id} className="group relative rounded-xl overflow-hidden bg-neutral-900 border border-neutral-800">
              <img
                src={work.coverUrl}
                alt={work.title}
                className="w-full h-80 object-cover group-hover:scale-105 transition-transform duration-500"
              />
              <div className="p-5">
                <h3 className="font-serif text-lg text-white">{work.title}</h3>
                <p className="text-xs text-neutral-400 capitalize mt-1">{work.category}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Direct WhatsApp Chat Action */}
      {data.whatsappEnabled && data.whatsappNumber && (
        <a
          href={`https://wa.me/${data.cleanWhatsappNumber || data.whatsappNumber}?text=${encodeURIComponent(
            data.whatsappPrefillMessage || 'Hello, I would like to inquire about booking.'
          )}`}
          target="_blank"
          rel="noreferrer"
          className="fixed bottom-6 right-6 px-4 py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-full shadow-2xl flex items-center gap-2 text-sm z-50 transition"
        >
          <span>Chat on WhatsApp</span>
        </a>
      )}
    </div>
  );
};
```

---

## ✅ Integration Verification Checklist

1. [ ] **Debouncing & Race Condition**: Ensure 400ms debounce with `AbortController` cancellation prevents stale responses from overwriting the latest input.
2. [ ] **202 Accepted Response**: Recognize `HTTP 202` on claim and transition UI to pending/provisioning state.
3. [ ] **4-Second Status Polling**: Automatically poll `/api/portfolio/subdomain/status/` while state is `pending` or `provisioning`.
4. [ ] **Retry Rate Limit Handling**: Correctly read `retry_after_seconds` on `HTTP 429` responses and display an active countdown timer.
5. [ ] **Public Tenant Ingress**: Verify that navigating to `https://<subdomain>.exshare.ai` calls `/api/public/portfolio-site/` anonymously and renders the custom showcase.
