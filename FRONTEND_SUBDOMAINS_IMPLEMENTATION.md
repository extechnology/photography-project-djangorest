# EX SHARE Atelier — Photographer Portfolio Subdomains
## Frontend Integration & UI Implementation Guide

This guide details the complete frontend implementation for **Photographer Subdomains** (e.g. `https://mridhul.exshare.ai`). It covers:
1. **Studio Dashboard**: Real-time debounced availability check, race-condition handling, and atomic claiming UI.
2. **Public Tenant App**: Dynamic host resolution, template rendering via relative APIs, and tenant-scoped inquiry/telemetry submission.
3. **Security & Session Isolation**: Host-only cookie isolation and deep-link handling.

---

## 1. Architectural Overview

```
                      ┌───────────────────────────────────────────┐
                      │ Wildcard Ingress: *.exshare.ai (Port 443) │
                      └─────────────────────┬─────────────────────┘
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    │                                               │
      (Tenant Visitor Host)                           (Dashboard Host)
     https://mridhul.exshare.ai                     https://app.exshare.ai
                    │                                               │
         Serves React SPA Dist                           Serves React SPA Dist
  (Tenant Mode: window.location.host)             (Studio Settings & Photo Proofing)
                    │                                               │
   Proxies /api/public/portfolio-site/            Authenticated API Requests:
     to Django (Host preserved)                   - GET  /api/portfolio/subdomain/availability/
                    │                             - PUT  /api/portfolio/subdomain/
                    ▼                                               ▼
     [Django Tenant Resolver View]                [Django Atomic Subdomain Claim Engine]
```

---

## 2. API Contract Reference

| Method | Endpoint | Access | Purpose | Payload / Parameters | Success Response (200 / 202) |
|---|---|---|---|---|---|
| `GET` | `/api/portfolio/subdomain/availability/` | Authenticated | Live availability query | `?name=mridhul` | `{"name":"mridhul", "available":true, "reason":null, "is_current_owner":false}` |
| `PUT` | `/api/portfolio/subdomain/` | Authenticated Owner | Atomically claim subdomain & enqueue DNS | `{"subdomain":"mridhul"}` | **202 Accepted**: `{"status":"pending", "subdomain":"mridhul", "domain":"mridhul.exshare.ai", "url":"https://mridhul.exshare.ai"}` |
| `GET` | `/api/portfolio/subdomain/status/` | Authenticated Owner | Check DNS provisioning health & status | None | `{"subdomain":"mridhul", "status":"active", "domain":"mridhul.exshare.ai", "url":"https://mridhul.exshare.ai", "error":null, "retry_allowed":false}` |
| `POST` | `/api/portfolio/subdomain/retry/` | Authenticated Owner | Retry failed DNS provisioning (throttled) | None | **202 Accepted**: `{"status":"pending", "subdomain":"mridhul", "message":"DNS provisioning retry scheduled."}` |
| `GET` | `/api/public/portfolio-site/` | Public Visitor | Retrieve published portfolio resolved from `Host` | None | Serialized `PortfolioConfig` with featured works & photos |
| `POST` | `/api/public/portfolio-site/inquiries/` | Public Visitor | Submit client inquiry bound to tenant | `{"client_name":"...", "client_email":"...", "message":"..."}` | `{"success":true, "inquiry_id": 42}` |
| `POST` | `/api/public/portfolio-site/track-view/` | Public Visitor | Record telemetry / view metrics | `{"page_section":"hero", "device":"desktop"}` | `{"success":true, "tracked":true}` |

---

## 3. Dashboard Component: Subdomain Setting & Claiming

Create or update `src/components/portfolio/PortfolioSubdomainSetting.tsx` in your React dashboard.

### Key Features Implemented:
- **Fixed `.exshare.ai` Suffix**: Clear visual branding cues.
- **400ms Debounce**: Protects backend resources and user quota.
- **Stale-Response Protection**: Uses sequence tokens and `AbortController` to guarantee slow network responses never override the latest user keystrokes.
- **Rich Status States**:
  - `idle`: Initial loaded state.
  - `checking`: Loading spinner.
  - `available`: Green indicator with claim button.
  - `taken`: Amber/red indicator ("Already claimed by another portfolio").
  - `reserved`: Amber warning ("Reserved system name").
  - `already_owned`: Blue badge ("Assigned to your portfolio").
  - `invalid`: Validation error message (length, character set).
- **Conflict Handling (HTTP 409)**: Alerts the photographer if another user claimed the name during a race condition.
- **Post-Claim Experience**: One-click "Copy URL" and "Visit Portfolio" external link.

### Source Code: `src/components/portfolio/PortfolioSubdomainSetting.tsx`

```tsx
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  Copy,
  ExternalLink,
  Globe,
  RefreshCw,
  Clock,
  Sparkles
} from 'lucide-react';

interface PortfolioSubdomainSettingProps {
  currentSubdomain?: string | null;
  currentStatus?: 'pending' | 'provisioning' | 'active' | 'failed' | null;
  onSubdomainUpdated?: (newSubdomain: string, fullUrl: string) => void;
}

type SubdomainAvailabilityState = 
  | 'idle'
  | 'checking'
  | 'available'
  | 'taken'
  | 'reserved'
  | 'invalid'
  | 'error';

type ProvisioningStatus = 'pending' | 'provisioning' | 'active' | 'failed';

export const PortfolioSubdomainSetting: React.FC<PortfolioSubdomainSettingProps> = ({
  currentSubdomain = '',
  currentStatus = null,
  onSubdomainUpdated,
}) => {
  const [subdomainInput, setSubdomainInput] = useState<string>(currentSubdomain || '');
  const [assignedSubdomain, setAssignedSubdomain] = useState<string>(currentSubdomain || '');
  const [provisioningStatus, setProvisioningStatus] = useState<ProvisioningStatus | null>(currentStatus || null);
  const [availabilityState, setAvailabilityState] = useState<SubdomainAvailabilityState>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isClaiming, setIsClaiming] = useState<boolean>(false);
  const [isRetrying, setIsRetrying] = useState<boolean>(false);
  const [retryCooldown, setRetryCooldown] = useState<number>(0);
  const [copied, setCopied] = useState<boolean>(false);

  // Stale-response & cancellation tracker
  const abortControllerRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef<number>(0);
  const statusPollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Sync initial props
  useEffect(() => {
    if (currentSubdomain) {
      setSubdomainInput(currentSubdomain);
      setAssignedSubdomain(currentSubdomain);
    }
    if (currentStatus) {
      setProvisioningStatus(currentStatus);
    }
  }, [currentSubdomain, currentStatus]);

  // Fetch initial provisioning status if a subdomain is already assigned
  useEffect(() => {
    if (assignedSubdomain && !provisioningStatus) {
      fetchStatus();
    }
  }, [assignedSubdomain]);

  // Polling hook: Poll status while pending or provisioning
  useEffect(() => {
    if (assignedSubdomain && (provisioningStatus === 'pending' || provisioningStatus === 'provisioning')) {
      statusPollTimerRef.current = setInterval(() => {
        fetchStatus();
      }, 3000);
    } else {
      if (statusPollTimerRef.current) {
        clearInterval(statusPollTimerRef.current);
        statusPollTimerRef.current = null;
      }
    }

    return () => {
      if (statusPollTimerRef.current) {
        clearInterval(statusPollTimerRef.current);
      }
    };
  }, [assignedSubdomain, provisioningStatus]);

  // Retry cooldown countdown timer
  useEffect(() => {
    if (retryCooldown <= 0) return;
    const interval = setInterval(() => {
      setRetryCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [retryCooldown]);

  const fetchStatus = async () => {
    try {
      const response = await axios.get('/api/portfolio/subdomain/status/');
      const data = response.data;
      if (data.subdomain) {
        setAssignedSubdomain(data.subdomain);
        setProvisioningStatus(data.status);
        if (data.error) {
          setErrorMessage(data.error);
        } else if (data.status === 'active') {
          setErrorMessage(null);
        }
      }
    } catch (err) {
      // Background poll silently fails
    }
  };

  // Client-side quick syntax validation
  const validateFormat = (name: string): { valid: boolean; error?: string } => {
    const clean = name.trim().toLowerCase();
    if (!clean) return { valid: false };
    if (clean.length < 3) return { valid: false, error: 'Must be at least 3 characters.' };
    if (clean.length > 63) return { valid: false, error: 'Cannot exceed 63 characters.' };
    if (clean.startsWith('-') || clean.endsWith('-')) return { valid: false, error: 'Cannot begin or end with a hyphen.' };
    if (clean.includes('.') || clean.includes('_') || clean.includes(' ') || clean.includes('/')) {
      return { valid: false, error: 'Dots, spaces, underscores, and URLs are not permitted.' };
    }
    if (!/^[a-z0-9-]+$/.test(clean)) return { valid: false, error: 'Only lowercase letters, numbers, and hyphens allowed.' };
    return { valid: true };
  };

  // Debounced availability check
  useEffect(() => {
    const clean = subdomainInput.trim().toLowerCase();

    // If input matches existing confirmed subdomain
    if (assignedSubdomain && clean === assignedSubdomain) {
      setAvailabilityState('idle');
      setErrorMessage(null);
      return;
    }

    if (!clean) {
      setAvailabilityState('idle');
      setErrorMessage(null);
      return;
    }

    const { valid, error } = validateFormat(clean);
    if (!valid) {
      setAvailabilityState('invalid');
      setErrorMessage(error || 'Invalid subdomain format.');
      return;
    }

    setAvailabilityState('checking');
    setErrorMessage(null);

    // Cancel pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const currentSeq = ++requestSeqRef.current;

    const timer = setTimeout(async () => {
      try {
        const response = await axios.get('/api/portfolio/subdomain/availability/', {
          params: { name: clean },
          signal: controller.signal,
        });

        // Ignore if a newer request was dispatched
        if (currentSeq !== requestSeqRef.current) return;

        const data = response.data;
        if (data.available) {
          setAvailabilityState('available');
          setErrorMessage(null);
        } else {
          if (data.reason === 'already_taken') {
            setAvailabilityState('taken');
            setErrorMessage('This subdomain is already claimed by another photographer.');
          } else if (data.reason?.includes('reserved')) {
            setAvailabilityState('reserved');
            setErrorMessage('This name is reserved for platform infrastructure.');
          } else {
            setAvailabilityState('invalid');
            setErrorMessage(data.reason || 'This name is unavailable.');
          }
        }
      } catch (err: any) {
        if (axios.isCancel(err)) return;
        if (currentSeq === requestSeqRef.current) {
          setAvailabilityState('error');
          setErrorMessage('Could not verify availability. Check network connection.');
        }
      }
    }, 400);

    return () => clearTimeout(timer);
  }, [subdomainInput, assignedSubdomain]);

  // Claim submission handler
  const handleClaim = async () => {
    const clean = subdomainInput.trim().toLowerCase();
    if (!clean || availabilityState !== 'available') return;

    setIsClaiming(true);
    setErrorMessage(null);

    try {
      const response = await axios.put('/api/portfolio/subdomain/', { subdomain: clean });
      const data = response.data;

      setAssignedSubdomain(data.subdomain);
      setProvisioningStatus(data.status || 'pending');
      setAvailabilityState('idle');

      if (onSubdomainUpdated) {
        onSubdomainUpdated(data.subdomain, data.url);
      }
    } catch (err: any) {
      if (err.response?.status === 409) {
        setAvailabilityState('taken');
        setErrorMessage('Another photographer just claimed this name! Please choose a different subdomain.');
      } else if (err.response?.status === 400 && err.response?.data?.code === 'RENAME_PROHIBITED') {
        setErrorMessage(err.response.data.error || 'Subdomain renaming is not permitted.');
      } else {
        setErrorMessage(err.response?.data?.error || 'Failed to claim subdomain. Please try again.');
      }
    } finally {
      setIsClaiming(false);
    }
  };

  // Retry failed provisioning handler
  const handleRetry = async () => {
    if (isRetrying || retryCooldown > 0) return;
    setIsRetrying(true);
    setErrorMessage(null);

    try {
      const response = await axios.post('/api/portfolio/subdomain/retry/');
      const data = response.data;
      setProvisioningStatus(data.status || 'pending');
      setRetryCooldown(30);
    } catch (err: any) {
      if (err.response?.status === 429) {
        const after = err.response.data?.retry_after_seconds || 30;
        setRetryCooldown(after);
        setErrorMessage(`Please wait ${after}s before retrying.`);
      } else {
        setErrorMessage(err.response?.data?.error || 'Retry request failed. Please check connection.');
      }
    } finally {
      setIsRetrying(false);
    }
  };

  const copyUrl = () => {
    if (!assignedSubdomain) return;
    const url = `https://${assignedSubdomain}.exshare.ai`;
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const previewName = subdomainInput.trim().toLowerCase() || 'yourstudio';

  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 text-white max-w-2xl shadow-xl">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-indigo-500/10 border border-indigo-500/20 rounded-lg text-indigo-400">
            <Globe className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-lg text-neutral-100 flex items-center gap-2">
              Signature Portfolio Subdomain
              <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-neutral-800 border border-neutral-700 text-neutral-400">
                GoDaddy Automated DNS
              </span>
            </h3>
            <p className="text-sm text-neutral-400">
              Publish your atelier website to your bespoke vanity address.
            </p>
          </div>
        </div>

        {/* Status Pill Badge */}
        {assignedSubdomain && (
          <div>
            {provisioningStatus === 'active' && (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <CheckCircle className="w-3.5 h-3.5" />
                Live & Verified
              </span>
            )}
            {(provisioningStatus === 'pending' || provisioningStatus === 'provisioning') && (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Provisioning DNS...
              </span>
            )}
            {provisioningStatus === 'failed' && (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                <XCircle className="w-3.5 h-3.5" />
                Setup Needed
              </span>
            )}
          </div>
        )}
      </div>

      {/* Input Group */}
      <div className="mt-4">
        <label className="block text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-2">
          Subdomain Prefix
        </label>
        
        <div className="flex items-center">
          <div className="relative flex-1">
            <input
              type="text"
              value={subdomainInput}
              onChange={(e) => setSubdomainInput(e.target.value)}
              disabled={isClaiming || provisioningStatus === 'active'}
              placeholder="mridhul"
              className={`w-full bg-neutral-950 border px-4 py-3 rounded-l-lg text-neutral-100 placeholder-neutral-600 focus:outline-none transition-colors ${
                availabilityState === 'available'
                  ? 'border-emerald-500/80 focus:border-emerald-500'
                  : availabilityState === 'taken' || availabilityState === 'invalid'
                  ? 'border-rose-500/80 focus:border-rose-500'
                  : provisioningStatus === 'active'
                  ? 'border-indigo-500/50 focus:border-indigo-500'
                  : 'border-neutral-800 focus:border-neutral-600'
              }`}
            />
          </div>

          <div className="bg-neutral-800/80 border border-l-0 border-neutral-700 px-4 py-3 rounded-r-lg text-neutral-400 font-mono text-sm select-none">
            .exshare.ai
          </div>
        </div>

        {/* Live URL Preview Indicator */}
        <div className="mt-2 text-xs text-neutral-400 flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
          <span>Live URL Preview:</span>
          <span className="font-mono text-neutral-200 underline decoration-neutral-700">
            https://{previewName}.exshare.ai
          </span>
        </div>

        {/* Real-time Status Messaging */}
        <div className="mt-3 flex items-center justify-between min-h-[28px]">
          <div className="flex items-center gap-2 text-sm">
            {availabilityState === 'checking' && (
              <span className="flex items-center gap-1.5 text-neutral-400">
                <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                Checking GoDaddy availability...
              </span>
            )}

            {availabilityState === 'available' && !assignedSubdomain && (
              <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                <CheckCircle className="w-4 h-4" />
                Available to claim!
              </span>
            )}

            {(availabilityState === 'taken' || availabilityState === 'reserved' || availabilityState === 'invalid') && (
              <span className="flex items-center gap-1.5 text-rose-400 font-medium">
                <XCircle className="w-4 h-4" />
                {errorMessage}
              </span>
            )}

            {availabilityState === 'error' && (
              <span className="flex items-center gap-1.5 text-amber-400 font-medium">
                <AlertCircle className="w-4 h-4" />
                {errorMessage}
              </span>
            )}

            {assignedSubdomain && provisioningStatus === 'provisioning' && (
              <span className="flex items-center gap-1.5 text-amber-400 text-xs">
                <Clock className="w-4 h-4 animate-spin" />
                Configuring DNS records on GoDaddy. This usually takes 10–30 seconds.
              </span>
            )}

            {assignedSubdomain && provisioningStatus === 'failed' && (
              <span className="flex items-center gap-1.5 text-rose-400 text-xs font-medium">
                <AlertCircle className="w-4 h-4" />
                {errorMessage || 'DNS record creation failed. Check API credentials or retry.'}
              </span>
            )}
          </div>

          {/* Action Buttons: Claim vs Retry vs Copy/Visit */}
          <div className="flex items-center gap-2">
            {availabilityState === 'available' && !assignedSubdomain && (
              <button
                type="button"
                onClick={handleClaim}
                disabled={isClaiming}
                className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-neutral-950 font-semibold rounded-lg text-sm transition-all flex items-center gap-1.5 shadow-md shadow-emerald-500/20"
              >
                {isClaiming ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Reserving...
                  </>
                ) : (
                  'Claim & Provision DNS'
                )}
              </button>
            )}

            {provisioningStatus === 'failed' && (
              <button
                type="button"
                onClick={handleRetry}
                disabled={isRetrying || retryCooldown > 0}
                className="px-3.5 py-1.5 bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                {isRetrying ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="w-3.5 h-3.5" />
                )}
                {retryCooldown > 0 ? `Wait ${retryCooldown}s` : 'Retry DNS Provisioning'}
              </button>
            )}

            {assignedSubdomain && provisioningStatus === 'active' && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={copyUrl}
                  className="px-3 py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors border border-neutral-700"
                >
                  <Copy className="w-3.5 h-3.5" />
                  {copied ? 'Copied!' : 'Copy Link'}
                </button>
                <a
                  href={`https://${assignedSubdomain}.exshare.ai`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-3 py-1.5 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors border border-indigo-500/30"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Visit Portfolio
                </a>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
```

---

## 4. Public Tenant Visitor Experience

When visitors navigate to `https://mridhul.exshare.ai`, Nginx serves the compiled SPA build. The React app detects that it is executing on a tenant host and switches to visitor showcase mode.

### Tenant Host Detection: `src/utils/tenantResolver.ts`

```typescript
export interface TenantInfo {
  isTenant: boolean;
  subdomain: string | null;
  baseDomain: string;
}

export function detectTenantHost(): TenantInfo {
  const hostname = window.location.hostname.toLowerCase();
  const baseDomain = 'exshare.ai';

  // Local development hostnames (e.g. mridhul.localhost:3000)
  if (hostname.endsWith('.localhost')) {
    const sub = hostname.replace('.localhost', '');
    return {
      isTenant: sub !== 'localhost' && !['app', 'api', 'admin', 'www'].includes(sub),
      subdomain: sub,
      baseDomain: 'localhost',
    };
  }

  // Production wildcard hostnames (e.g. mridhul.exshare.ai)
  if (hostname.endsWith(`.${baseDomain}`)) {
    const sub = hostname.replace(`.${baseDomain}`, '');
    const reserved = ['app', 'api', 'admin', 'auth', 'www', 'cdn', 'static', 'mail', 'support', 'staging'];
    
    // Disallow multi-level or reserved service hosts
    if (sub.includes('.') || reserved.includes(sub)) {
      return { isTenant: false, subdomain: null, baseDomain };
    }

    return {
      isTenant: true,
      subdomain: sub,
      baseDomain,
    };
  }

  return { isTenant: false, subdomain: null, baseDomain };
}
```

### Public Showcase Data Loader: `src/pages/PublicTenantPortfolioPage.tsx`

```tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Loader2, AlertCircle } from 'lucide-react';
import { EditorialTemplate } from '../templates/EditorialTemplate';
import { MasonryTemplate } from '../templates/MasonryTemplate';
import { CinematicTemplate } from '../templates/CinematicTemplate';
import { MinimalTemplate } from '../templates/MinimalTemplate';

export const PublicTenantPortfolioPage: React.FC = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [portfolio, setPortfolio] = useState<any | null>(null);
  const [notFound, setNotFound] = useState<boolean>(false);

  useEffect(() => {
    // Relative request: Nginx proxies to Django preserving Host
    axios.get('/api/public/portfolio-site/')
      .then((res) => {
        setPortfolio(res.data);
        setNotFound(false);

        // Record visitor telemetry
        axios.post('/api/public/portfolio-site/track-view/', {
          page_section: 'hero',
          device: window.innerWidth < 768 ? 'mobile' : 'desktop',
        }).catch(() => {});
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setNotFound(true);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-black flex flex-col items-center justify-center text-white">
        <Loader2 className="w-8 h-8 animate-spin text-neutral-400 mb-4" />
        <p className="text-neutral-500 text-sm tracking-widest uppercase">Loading Portfolio...</p>
      </div>
    );
  }

  if (notFound || !portfolio) {
    return (
      <div className="min-h-screen bg-neutral-950 flex flex-col items-center justify-center text-white p-6 text-center">
        <div className="p-4 bg-neutral-900 border border-neutral-800 rounded-full mb-6">
          <AlertCircle className="w-10 h-10 text-neutral-400" />
        </div>
        <h1 className="text-3xl font-serif mb-2">Portfolio Not Found</h1>
        <p className="text-neutral-400 max-w-md text-sm mb-8">
          The showcase you are looking for has not been published or does not exist.
        </p>
        <a
          href="https://exshare.ai"
          className="px-6 py-2.5 bg-neutral-800 hover:bg-neutral-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          Return to EX SHARE
        </a>
      </div>
    );
  }

  // Render configured signature template
  const templateId = portfolio.template_id || portfolio.templateId || 'darkroom-atelier';

  switch (templateId) {
    case 'editorial':
    case 'editorial-vogue':
      return <EditorialTemplate portfolio={portfolio} isPublicTenant />;
    case 'cinematic':
    case 'cinematic-luxury':
      return <CinematicTemplate portfolio={portfolio} isPublicTenant />;
    case 'minimal':
    case 'minimal-zen':
      return <MinimalTemplate portfolio={portfolio} isPublicTenant />;
    case 'masonry':
    case 'darkroom-atelier':
    default:
      return <MasonryTemplate portfolio={portfolio} isPublicTenant />;
  }
};
```

---

## 5. Public Inquiry Submission on Tenant Hosts

When a client submits an inquiry through a tenant website:
- Use the tenant relative endpoint: `POST /api/public/portfolio-site/inquiries/`
- **Do not send `photographer_id`**. The backend securely determines ownership directly from the server `Host` header.

```typescript
export async function submitTenantInquiry(formData: {
  client_name: string;
  client_email: string;
  client_phone?: string;
  event_type: string;
  event_date?: string;
  location?: string;
  budget?: string;
  message: string;
}) {
  const response = await axios.post('/api/public/portfolio-site/inquiries/', formData);
  return response.data;
}
```

---

## 6. Security & Cookie Hygiene Checklist

1. **Host-Only Cookies**:
   - `SESSION_COOKIE_DOMAIN = None` and `CSRF_COOKIE_DOMAIN = None` remain default.
   - Authentication cookies from `app.exshare.ai` are **never sent** to `mridhul.exshare.ai`.
2. **Visitor Privacy**:
   - Visitors on `*.exshare.ai` are never prompted for JWT authorization headers.
   - Public APIs (`/api/public/portfolio-site/`) allow anonymous access (`AllowAny`).
3. **No Cross-Tenant Data Leaks**:
   - The frontend never passes a client-side photographer ID parameter on tenant routes.
   - Any attempt to access another tenant's project or inquiry results in immediate server-side 404.
