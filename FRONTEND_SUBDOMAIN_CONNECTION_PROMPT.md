# PROMPT: Connect Frontend to ExShare Dynamic Portfolio Subdomain & Showcase APIs

> **Instructions for Frontend AI Agent / Developer:**
> You are tasked with integrating the React / Next.js frontend with the Django REST Framework backend for **ExShare** (`exshare.ai`).
> The backend handles dynamic subdomain reservation, instant wildcard activation, studio settings, and public portfolio resolution (via both path `/api/public/portfolios/<slug>/` and wildcard host routing `https://<subdomain>.exshare.ai`).
>
> Follow the exact API contracts, TypeScript types, hooks, and routing logic detailed below.

---

## 1. Backend Architecture & Environment Setup

- **Main Platform Domain:** `exshare.ai`
- **Backend API Base URL:** `https://server.exshare.ai` (or `process.env.NEXT_PUBLIC_API_URL` / `import.meta.env.VITE_API_URL`)
- **Photographer Live URL Format:** `https://{subdomain}.exshare.ai` (e.g. `https://mrudul.exshare.ai`)
- **DNS Architecture:** Instant Wildcard DNS (`*.exshare.ai`). Subdomains become active immediately upon claiming without background delay or third-party DNS provisioning calls.

---

## 2. TypeScript Data Models

Create or update `types/portfolio.ts`:

```typescript
// types/portfolio.ts

export type SubdomainStatus = 'pending' | 'provisioning' | 'active' | 'failed';

export interface SubdomainAvailabilityResponse {
  subdomain: string;
  available: boolean;
  url: string;
  message: string;
  name?: string;
  reason?: 'already_taken' | 'reserved' | 'invalid_format' | null;
  error?: string;
  is_current_owner?: boolean;
  domain?: string;
  live_url?: string;
}

export interface ClaimSubdomainResponse {
  status: 'active' | 'pending';
  subdomain: string;
  domain: string;
  url: string;
  live_url: string;
  direct_url: string;
  message: string;
}

export interface PortfolioWorkPhoto {
  id: number;
  photoUrl: string;
  photo_url?: string;
  caption?: string;
  order: number;
}

export interface PortfolioWork {
  id: string | number;
  title: string;
  category: 'weddings' | 'editorial' | 'commercial' | 'pre-wedding' | 'cinematic' | 'portrait';
  coverUrl: string;
  cover_url?: string;
  year?: string;
  location?: string;
  description?: string;
  clientName?: string;
  client_name?: string;
  order: number;
  mediaCount: number;
  highlightMedia: string[];
  photos?: PortfolioWorkPhoto[];
}

export interface PortfolioConfig {
  id: number;
  photographerId: number;
  studioName: string;
  artistName: string;
  tagline: string;
  bio: string;
  aboutStory: string;
  location: string;
  avatarUrl: string;
  bannerUrl: string;
  contactEmail: string;
  contactPhone: string;
  instagramHandle: string;
  youtubeHandle: string;
  websiteUrl: string;
  templateId: 'editorial-vogue' | 'darkroom-atelier' | 'cinematic-luxury' | 'minimal-zen';
  subdomain: string | null;
  subdomainStatus: SubdomainStatus;
  customDomain?: string | null;
  isPublished: boolean;
  isBookingOpen: boolean;
  portfolioUrl: string;
  fullDomain: string;
  featuredWorks: PortfolioWork[];
  accentColor?: string;
  pricingStartingAt?: string;
  philosophyQuote?: string;
  philosophyAuthor?: string;
  whatsappEnabled?: boolean;
  whatsappNumber?: string;
  whatsappPrefillMessage?: string;
}
```

---

## 3. API Client Methods

Create `services/portfolioApi.ts`:

```typescript
// services/portfolioApi.ts
import axios from 'axios';
import {
  SubdomainAvailabilityResponse,
  ClaimSubdomainResponse,
  PortfolioConfig,
} from '../types/portfolio';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'https://server.exshare.ai';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

/**
 * 1. Debounced Availability Check
 * Checks if requested subdomain is valid, unreserved, and available in DB.
 */
export async function checkSubdomainAvailability(
  subdomain: string,
  token?: string
): Promise<SubdomainAvailabilityResponse> {
  const clean = subdomain.trim().toLowerCase();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const response = await apiClient.get<SubdomainAvailabilityResponse>(
    `/api/portfolio/subdomain/availability/`,
    {
      params: { subdomain: clean },
      headers,
    }
  );
  return response.data;
}

/**
 * 2. Claim Subdomain
 * Concurrency-safe atomic reservation with immediate wildcard activation.
 */
export async function claimSubdomain(
  subdomain: string,
  token: string
): Promise<ClaimSubdomainResponse> {
  const clean = subdomain.trim().toLowerCase();
  const response = await apiClient.post<ClaimSubdomainResponse>(
    `/api/portfolio/subdomain/`,
    { subdomain: clean },
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
  return response.data;
}

/**
 * 3. Update Portfolio Studio Settings (Branding, Template, Publishing)
 */
export async function updatePortfolioConfig(
  payload: Partial<PortfolioConfig>,
  token: string
): Promise<PortfolioConfig> {
  const response = await apiClient.patch<PortfolioConfig>(
    `/api/portfolio/config/`,
    payload,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
  return response.data;
}

/**
 * 4. Fetch Public Portfolio by Subdomain or Username (Path-Based)
 * Use when routing inside the main app e.g., exshare.ai/p/mrudul
 */
export async function fetchPublicPortfolio(
  identifier: string
): Promise<PortfolioConfig> {
  const clean = encodeURIComponent(identifier.trim().toLowerCase());
  const response = await apiClient.get<PortfolioConfig>(
    `/api/public/portfolios/${clean}/`
  );
  return response.data;
}

/**
 * 5. Fetch Tenant Portfolio (Host / Wildcard Domain Resolution)
 * Use when rendering visitor traffic at https://mrudul.exshare.ai
 */
export async function fetchTenantPortfolioSite(
  overrideSubdomain?: string
): Promise<PortfolioConfig> {
  const headers: Record<string, string> = {};
  if (overrideSubdomain) {
    headers['X-Tenant-Subdomain'] = overrideSubdomain;
  }

  const response = await apiClient.get<PortfolioConfig>(
    `/api/public/portfolio-site/`,
    { headers }
  );
  return response.data;
}
```

---

## 4. Reusable React Hook: `useSubdomainCheck`

Create `hooks/useSubdomainCheck.ts` with built-in 400ms debounce and RFC 1035 format validation:

```typescript
// hooks/useSubdomainCheck.ts
import { useState, useEffect } from 'react';
import { checkSubdomainAvailability } from '../services/portfolioApi';
import { SubdomainAvailabilityResponse } from '../types/portfolio';

const SUBDOMAIN_REGEX = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$/;
const RESERVED_CLIENT_LIST = new Set([
  'admin', 'api', 'app', 'www', 'static', 'media', 'dashboard',
  'billing', 'login', 'signup', 'register', 'root', 'exshare', 'support'
]);

export function useSubdomainCheck(token?: string, currentSubdomain?: string | null) {
  const [subdomain, setSubdomain] = useState('');
  const [debouncedValue, setDebouncedValue] = useState('');
  const [isChecking, setIsChecking] = useState(false);
  const [result, setResult] = useState<SubdomainAvailabilityResponse | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);

  // 1. Debounce input
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(subdomain.trim().toLowerCase());
    }, 400);
    return () => clearTimeout(handler);
  }, [subdomain]);

  // 2. Perform validation and backend lookup
  useEffect(() => {
    if (!debouncedValue) {
      setResult(null);
      setClientError(null);
      return;
    }

    // Client-side quick checks
    if (debouncedValue.length < 3) {
      setClientError('Must be at least 3 characters long');
      setResult(null);
      return;
    }
    if (debouncedValue.length > 63) {
      setClientError('Cannot exceed 63 characters');
      setResult(null);
      return;
    }
    if (debouncedValue.startsWith('-') || debouncedValue.endsWith('-')) {
      setClientError('Cannot start or end with a hyphen');
      setResult(null);
      return;
    }
    if (!SUBDOMAIN_REGEX.test(debouncedValue)) {
      setClientError('Only lowercase letters, numbers, and hyphens allowed');
      setResult(null);
      return;
    }
    if (RESERVED_CLIENT_LIST.has(debouncedValue)) {
      setClientError(`'${debouncedValue}' is reserved for platform infrastructure`);
      setResult(null);
      return;
    }

    setClientError(null);

    // If matches user's current active subdomain
    if (currentSubdomain && currentSubdomain.toLowerCase() === debouncedValue) {
      setResult({
        subdomain: debouncedValue,
        available: true,
        url: `https://${debouncedValue}.exshare.ai`,
        message: 'Currently assigned to your studio',
        is_current_owner: true,
      });
      return;
    }

    // Query backend API
    let isCancelled = false;
    setIsChecking(true);

    checkSubdomainAvailability(debouncedValue, token)
      .then((data) => {
        if (!isCancelled) {
          setResult(data);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          setResult({
            subdomain: debouncedValue,
            available: false,
            url: `https://${debouncedValue}.exshare.ai`,
            message: err.response?.data?.message || err.response?.data?.error || 'Validation error',
            reason: 'invalid_format',
          });
        }
      })
      .finally(() => {
        if (!isCancelled) setIsChecking(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [debouncedValue, token, currentSubdomain]);

  return {
    subdomain,
    setSubdomain,
    isChecking,
    result,
    clientError,
    isValid: Boolean(result?.available && !clientError),
  };
}
```

---

## 5. Subdomain Claiming UI Component

Drop this component into your Studio Dashboard / Settings:

```tsx
// components/SubdomainSettingsCard.tsx
import React, { useState } from 'react';
import { useSubdomainCheck } from '../hooks/useSubdomainCheck';
import { claimSubdomain } from '../services/portfolioApi';

interface Props {
  initialSubdomain: string | null;
  authToken: string;
  onSuccess?: (newSubdomain: string, liveUrl: string) => void;
}

export const SubdomainSettingsCard: React.FC<Props> = ({
  initialSubdomain,
  authToken,
  onSuccess,
}) => {
  const {
    subdomain,
    setSubdomain,
    isChecking,
    result,
    clientError,
    isValid,
  } = useSubdomainCheck(authToken, initialSubdomain);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleClaim = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || isSubmitting) return;

    setIsSubmitting(true);
    setSubmitMessage(null);

    try {
      const res = await claimSubdomain(subdomain, authToken);
      setSubmitMessage({
        type: 'success',
        text: `Success! Your portfolio is now live at ${res.url}`,
      });
      if (onSuccess) {
        onSuccess(res.subdomain, res.url);
      }
    } catch (err: any) {
      setSubmitMessage({
        type: 'error',
        text: err.response?.data?.error || err.response?.data?.message || 'Failed to claim subdomain',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6 text-white max-w-xl">
      <div className="mb-4">
        <h3 className="text-xl font-semibold tracking-tight">Studio Subdomain</h3>
        <p className="text-sm text-neutral-400 mt-1">
          Publish your photography portfolio with your custom branded URL on ExShare.
        </p>
      </div>

      <form onSubmit={handleClaim} className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-neutral-300 uppercase tracking-wider mb-2">
            Portfolio Address
          </label>
          <div className="flex items-center rounded-xl bg-black/60 border border-neutral-750 px-3 py-2.5 focus-within:border-amber-400 transition-colors">
            <span className="text-neutral-500 select-none text-sm">https://</span>
            <input
              type="text"
              value={subdomain}
              onChange={(e) => setSubdomain(e.target.value)}
              placeholder={initialSubdomain || 'yourstudio'}
              className="bg-transparent border-none text-white focus:outline-none px-1 text-sm font-medium w-full"
            />
            <span className="text-amber-400/90 font-medium select-none text-sm">.exshare.ai</span>
          </div>

          {/* Validation Feedback */}
          <div className="mt-2 min-h-5 text-xs">
            {isChecking && <span className="text-neutral-400 animate-pulse">Checking availability...</span>}
            {clientError && <span className="text-rose-400 font-medium">{clientError}</span>}
            {!isChecking && !clientError && result && (
              <span className={result.available ? 'text-emerald-400 font-medium' : 'text-rose-400 font-medium'}>
                {result.message}
              </span>
            )}
          </div>
        </div>

        {/* Live URL Preview */}
        {subdomain && isValid && (
          <div className="p-3 bg-neutral-950/80 rounded-lg border border-neutral-800/80 text-xs text-neutral-300 flex items-center justify-between">
            <span>Live URL:</span>
            <a
              href={`https://${subdomain}.exshare.ai`}
              target="_blank"
              rel="noreferrer"
              className="text-amber-400 hover:underline font-mono"
            >
              https://{subdomain}.exshare.ai
            </a>
          </div>
        )}

        {submitMessage && (
          <div
            className={`p-3 rounded-lg text-xs font-medium ${
              submitMessage.type === 'success'
                ? 'bg-emerald-950/50 text-emerald-300 border border-emerald-800'
                : 'bg-rose-950/50 text-rose-300 border border-rose-800'
            }`}
          >
            {submitMessage.text}
          </div>
        )}

        <button
          type="submit"
          disabled={!isValid || isSubmitting || isChecking}
          className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-amber-400 to-amber-500 hover:from-amber-300 hover:to-amber-400 text-neutral-950 font-semibold text-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-amber-500/10"
        >
          {isSubmitting ? 'Activating Subdomain...' : 'Claim & Publish Portfolio'}
        </button>
      </form>
    </div>
  );
};
```

---

## 6. Next.js Wildcard Multi-Tenant Routing (Optional)

If running a Next.js frontend with Wildcard DNS (`*.exshare.ai`), use `middleware.ts` to rewrite subdomains to a dynamic page:

```typescript
// middleware.ts
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(req: NextRequest) {
  const hostname = req.headers.get('host') || '';
  const baseDomain = 'exshare.ai';

  // Extract subdomain (e.g. mrudul.exshare.ai -> mrudul)
  const isSubdomain = hostname.endsWith(`.${baseDomain}`) && !hostname.startsWith('www.');

  if (isSubdomain) {
    const subdomain = hostname.replace(`.${baseDomain}`, '').split(':')[0].toLowerCase();
    const url = req.nextUrl.clone();
    // Rewrite internally to /_tenant/[subdomain]
    url.pathname = `/_tenant/${subdomain}${url.pathname}`;
    return NextResponse.rewrite(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
```

And in `app/_tenant/[subdomain]/page.tsx`:

```tsx
// app/_tenant/[subdomain]/page.tsx
import { notFound } from 'next/navigation';
import { fetchTenantPortfolioSite } from '../../../../services/portfolioApi';

export default async function TenantShowcasePage({
  params,
}: {
  params: { subdomain: string };
}) {
  try {
    const portfolio = await fetchTenantPortfolioSite(params.subdomain);
    return (
      <main className="min-h-screen bg-black text-white">
        <header className="p-8 text-center border-b border-neutral-900">
          <h1 className="text-4xl font-serif tracking-wide">{portfolio.studioName}</h1>
          <p className="text-neutral-400 mt-2">{portfolio.artistName} • {portfolio.tagline}</p>
        </header>

        {/* Featured Projects Grid */}
        <section className="max-w-7xl mx-auto p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {portfolio.featuredWorks?.map((work) => (
            <div key={work.id} className="group relative rounded-xl overflow-hidden bg-neutral-900">
              <img
                src={work.coverUrl}
                alt={work.title}
                className="w-full h-80 object-cover group-hover:scale-105 transition-transform duration-500"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent p-4 flex flex-col justify-end">
                <span className="text-xs uppercase tracking-widest text-amber-400">{work.category}</span>
                <h3 className="text-lg font-medium">{work.title}</h3>
              </div>
            </div>
          ))}
        </section>
      </main>
    );
  } catch (error: any) {
    notFound(); // Triggers Next.js 404 page for unpublished or non-existent portfolios
  }
}
```

---

## 7. Key Frontend Rules & Requirements Summary

1. **Case Normalization:** Always run `.trim().toLowerCase()` before passing subdomain strings.
2. **Instant Activation:** When `claimSubdomain` returns `status: "active"`, notify the user that their site is live immediately. No polling or DNS propagation wait required.
3. **404 Handling:** If the public endpoint returns `404`, display a polite "Portfolio is private or does not exist" view.
4. **Debounce:** Ensure availability queries are debounced by at least 350ms to 400ms to preserve rate-limiting quotas (45/min).
