# ⚡ FRONTEND IMPLEMENTATION SPECIFICATION: EX SHARE MASTER ADMIN DASHBOARD

> **Document File**: `dashboard_.md`  
> **Target Audience**: Senior Frontend Engineer / Full-Stack Developer / AI Coding Agent  
> **Target Tech Stack**: Next.js 14+ (App Router) or Vite + React 18/19, TypeScript, Tailwind CSS, Lucide Icons, Recharts / Tremor, TanStack Query (React Query) or SWR, Axios / Fetch  
> **Backend Base URL**: `https://server.exshare.ai` (or `/api` via reverse proxy)  
> **Security Clearance**: Master Administrator (`is_superuser`, `is_staff`, or `role: "admin"` / `"staff"`)

---

## 1. Executive Summary & Platform Architecture

**EX SHARE Atelier** is an enterprise-grade cloud photography platform serving professional studios, wedding photographers, high-fashion ateliers, and their clients. The platform encompasses:
1. **Photographer Studios & Portfolios**: Independent tenant subdomains (`<subdomain>.exshare.ai`), automated BigRock DNS routing, client booking CRM, and custom studio watermarking.
2. **Client Proofing & Galleries**: 4K video embedding, client selections, mobile-friendly guest liking with Email + OTP authentication, and automated ZIP packaging.
3. **Smart AI Tools**: AI-assisted photo culling, facial embedding clustering, and selfie face discovery for live event photo sharing.
4. **Subscription & Billing Engine**: Tiered subscription plans (Standard, Premium Elite, Custom) billed monthly, quarterly, or annually via Razorpay with automatic expiry lockouts.

This specification documents the frontend connection for the **Platform Master Admin Dashboard**, allowing administrators to monitor platform-wide KPIs, user growth, revenue/MRR, active subscriptions, storage usage, and recent activity.

---

## 2. API Endpoints Contract

All endpoints are hosted under `/api/admin/dashboard/` and require bearer authentication with administrator or staff privileges (`is_staff: true` or `is_superuser: true` or `role: "admin"`).

| Method | Endpoint | Access | Purpose | Query Params |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/admin/dashboard/overview/` | Admin / Staff | Master executive summary, KPIs, time-series charts, subscription breakdown, storage leaderboard, recent signups & payments | `days` *(integer: 7, 30, 90, 365. Default: `30`)* |
| `GET` | `/api/admin/dashboard/users/` | Admin / Staff | Paginated, searchable, and filterable table of all platform users & studios | `search`, `role`, `status`, `page`, `page_size`, `ordering` |
| `GET` | `/api/admin/dashboard/payments/` | Admin / Staff | Paginated transaction audit log with revenue filter summaries | `search`, `status`, `start_date`, `end_date`, `page`, `page_size`, `ordering` |
| `GET` | `/api/admin/dashboard/growth/` | Admin / Staff | Granular time-series growth curves (user registrations, gallery creation, and revenue) | `range` *(`7d`, `30d`, `90d`, `1y`. Default: `30d`)* |

---

## 3. API Response Schemas & Examples

### 3.1. Executive Overview (`GET /api/admin/dashboard/overview/?days=30`)

```json
{
  "status": "success",
  "time_window_days": 30,
  "kpis": {
    "total_users": 1248,
    "new_users_window": 184,
    "new_users_7d": 42,
    "new_users_today": 8,
    "user_growth_percentage": 24.3,
    "total_photographers": 890,
    "active_subscribers": 612,
    "churned_subscribers": 48,
    "total_revenue": 2450000.00,
    "revenue_window": 420000.00,
    "revenue_growth_percentage": 18.7,
    "mrr": 315000.00,
    "arr": 3780000.00,
    "avg_order_value": 4003.27,
    "total_galleries": 4520,
    "published_galleries": 3810,
    "total_media_items": 348200,
    "total_storage_used_bytes": 1099511627776,
    "total_storage_used_gb": 1024.0,
    "total_live_events": 165,
    "total_guest_viewers": 14200,
    "total_photo_likes": 89400,
    "total_inquiries": 3120
  },
  "user_growth": {
    "time_series": [
      {
        "date": "2026-09-16",
        "new_users": 5,
        "cumulative_users": 1069
      },
      {
        "date": "2026-10-15",
        "new_users": 8,
        "cumulative_users": 1248
      }
    ],
    "roles": {
      "photographer": 890,
      "user": 346,
      "staff": 8,
      "admin": 4
    },
    "verification_rates": {
      "email_verified_count": 998,
      "email_verified_percentage": 80.0,
      "phone_verified_count": 624,
      "phone_verified_percentage": 50.0
    }
  },
  "revenue_analytics": {
    "currency": "INR",
    "time_series": [
      {
        "date": "2026-09-16",
        "revenue": 14999.00,
        "transactions": 3
      },
      {
        "date": "2026-10-15",
        "revenue": 24500.00,
        "transactions": 5
      }
    ],
    "payment_status": {
      "success": 580,
      "pending": 24,
      "failed": 12,
      "total": 616
    },
    "gateways": {
      "razorpay": 616
    }
  },
  "subscriptions": {
    "by_tier": [
      {
        "tier": "standard",
        "label": "Standard",
        "count": 340,
        "percentage": 55.6
      },
      {
        "tier": "premium",
        "label": "Premium Elite",
        "count": 242,
        "percentage": 39.5
      },
      {
        "tier": "custom",
        "label": "Custom",
        "count": 30,
        "percentage": 4.9
      }
    ],
    "by_billing_cycle": [
      { "cycle": "quarterly", "count": 350 },
      { "cycle": "annual", "count": 182 },
      { "cycle": "monthly", "count": 80 }
    ],
    "by_status": {
      "active": 612,
      "expired": 42,
      "cancelled": 6
    }
  },
  "storage": {
    "total_bytes": 1099511627776,
    "total_gb": 1024.0,
    "photos_count": 342000,
    "videos_count": 6200,
    "top_studios": [
      {
        "id": 12,
        "studio_name": "Lumière Wedding Atelier",
        "photographer_name": "Henri Cartier",
        "email": "henri@lumiere.com",
        "used_bytes": 145000000000,
        "used_gb": 135.04,
        "gallery_count": 48
      }
    ]
  },
  "recent_payments": [
    {
      "id": "7f139d1b-7a31-419b-b2f5-b3e6e659e984",
      "gateway_order_id": "order_RZP9812401",
      "gateway_payment_id": "pay_RZP7102941",
      "amount": "4500.00",
      "currency": "INR",
      "gateway": "razorpay",
      "status": "success",
      "invoice_url": "https://server.exshare.ai/media/invoices/inv_01.pdf",
      "paid_at": "2026-10-15T11:20:00Z",
      "created_at": "2026-10-15T11:18:00Z",
      "user_id": 42,
      "user_email": "arthur@saint-denis.com",
      "studio_name": "Saint Denis Studio",
      "plan_name": "Standard Quarterly",
      "plan_tier": "standard",
      "plan_cycle": "quarterly"
    }
  ],
  "recent_users": [
    {
      "id": 1024,
      "email": "sarah.connor@skyline.art",
      "username": "sarah_connor",
      "fullname": "Sarah Connor",
      "role": "photographer",
      "studio_name": "Skyline Fine Art Atelier",
      "date_joined": "2026-10-15T14:30:00Z",
      "is_active": true,
      "is_email_verified": true
    }
  ],
  "system_health": {
    "status": "operational",
    "database": "connected",
    "server_time": "2026-10-16T09:30:00Z"
  }
}
```

---

### 3.2. Users Directory (`GET /api/admin/dashboard/users/?page=1&page_size=20&search=atelier`)

```json
{
  "count": 45,
  "next": "https://server.exshare.ai/api/admin/dashboard/users/?page=2",
  "previous": null,
  "results": [
    {
      "id": 89,
      "unique_id": "550e8400-e29b-41d4-a716-446655440000",
      "username": "mridhul",
      "email": "mridhul@exshare.ai",
      "phone": "+919876543210",
      "fullname": "Mridhul Radhakrishnan",
      "role": "photographer",
      "studio_name": "ExMedia Atelier",
      "plan_name": "Premium Elite (Annual)",
      "subscription_status": "active",
      "storage_used_bytes": 45182900000,
      "storage_used_gb": 42.08,
      "galleries_count": 28,
      "is_active": true,
      "is_staff": false,
      "is_superuser": false,
      "is_email_verified": true,
      "is_phone_verified": true,
      "date_joined": "2026-08-10T12:00:00Z",
      "last_login": "2026-10-16T08:15:00Z"
    }
  ]
}
```

---

### 3.3. Payments Audit Log (`GET /api/admin/dashboard/payments/?status=success&page=1`)

```json
{
  "count": 580,
  "next": "https://server.exshare.ai/api/admin/dashboard/payments/?page=2",
  "previous": null,
  "summary": {
    "filtered_total_successful_revenue": 2450000.0,
    "currency": "INR"
  },
  "results": [
    {
      "id": "a9f82d1c-4b5a-4e89-b7b3-8a9d12345678",
      "gateway_order_id": "order_Qz981K",
      "gateway_payment_id": "pay_Qz981K901",
      "amount": "14999.00",
      "currency": "INR",
      "gateway": "razorpay",
      "status": "success",
      "invoice_url": "https://server.exshare.ai/media/invoices/inv_890.pdf",
      "paid_at": "2026-10-15T09:40:00Z",
      "created_at": "2026-10-15T09:38:00Z",
      "user_id": 89,
      "user_email": "mridhul@exshare.ai",
      "studio_name": "ExMedia Atelier",
      "plan_name": "Premium Elite",
      "plan_tier": "premium",
      "plan_cycle": "annual"
    }
  ]
}
```

---

## 4. TypeScript Interfaces & Data Models

Place these types in `src/types/adminDashboard.ts`:

```typescript
// src/types/adminDashboard.ts

export type UserRole = 'admin' | 'staff' | 'photographer' | 'user';
export type SubscriptionStatus = 'active' | 'expired' | 'pending' | 'cancelled' | 'trial' | 'past_due' | 'none';
export type PaymentStatus = 'success' | 'pending' | 'failed';
export type PlanTier = 'standard' | 'premium' | 'custom';
export type BillingCycle = 'monthly' | 'quarterly' | 'annual';

export interface AdminKPIs {
  total_users: number;
  new_users_window: number;
  new_users_7d: number;
  new_users_today: number;
  user_growth_percentage: number;
  total_photographers: number;
  active_subscribers: number;
  churned_subscribers: number;
  total_revenue: number;
  revenue_window: number;
  revenue_growth_percentage: number;
  mrr: number;
  arr: number;
  avg_order_value: number;
  total_galleries: number;
  published_galleries: number;
  total_media_items: number;
  total_storage_used_bytes: number;
  total_storage_used_gb: number;
  total_live_events: number;
  total_guest_viewers: number;
  total_photo_likes: number;
  total_inquiries: number;
}

export interface UserGrowthPoint {
  date: string; // "YYYY-MM-DD"
  new_users: number;
  cumulative_users: number;
}

export interface UserGrowthAnalytics {
  time_series: UserGrowthPoint[];
  roles: Record<UserRole, number>;
  verification_rates: {
    email_verified_count: number;
    email_verified_percentage: number;
    phone_verified_count: number;
    phone_verified_percentage: number;
  };
}

export interface RevenuePoint {
  date: string;
  revenue: number;
  transactions: number;
}

export interface RevenueAnalytics {
  currency: string;
  time_series: RevenuePoint[];
  payment_status: {
    success: number;
    pending: number;
    failed: number;
    total: number;
  };
  gateways: Record<string, number>;
}

export interface PlanTierDistribution {
  tier: string;
  label: string;
  count: number;
  percentage: number;
}

export interface SubscriptionAnalytics {
  by_tier: PlanTierDistribution[];
  by_billing_cycle: { cycle: BillingCycle; count: number }[];
  by_status: Record<string, number>;
}

export interface TopStorageStudio {
  id: number;
  studio_name: string;
  photographer_name: string;
  email: string;
  used_bytes: number;
  used_gb: number;
  gallery_count: number;
}

export interface StorageAnalytics {
  total_bytes: number;
  total_gb: number;
  photos_count: number;
  videos_count: number;
  top_studios: TopStorageStudio[];
}

export interface AdminPaymentItem {
  id: string;
  gateway_order_id: string;
  gateway_payment_id: string;
  amount: string;
  currency: string;
  gateway: string;
  status: PaymentStatus;
  invoice_url: string | null;
  paid_at: string | null;
  created_at: string;
  user_id: number | null;
  user_email: string;
  studio_name: string;
  plan_name: string;
  plan_tier: string;
  plan_cycle: string;
}

export interface AdminUserItem {
  id: number;
  unique_id: string;
  username: string | null;
  email: string | null;
  phone: string | null;
  fullname: string | null;
  role: UserRole;
  studio_name: string;
  plan_name: string;
  subscription_status: SubscriptionStatus;
  storage_used_bytes: number;
  storage_used_gb: number;
  galleries_count: number;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  is_email_verified: boolean;
  is_phone_verified: boolean;
  date_joined: string;
  last_login: string | null;
}

export interface AdminDashboardOverviewResponse {
  status: 'success';
  time_window_days: number;
  kpis: AdminKPIs;
  user_growth: UserGrowthAnalytics;
  revenue_analytics: RevenueAnalytics;
  subscriptions: SubscriptionAnalytics;
  storage: StorageAnalytics;
  recent_payments: AdminPaymentItem[];
  recent_users: AdminUserItem[];
  system_health: {
    status: string;
    database: string;
    server_time: string;
  };
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  summary?: {
    filtered_total_successful_revenue: number;
    currency: string;
  };
  results: T[];
}
```

---

## 5. UI/UX Design System & Theme Aesthetics

To reflect the ultra-premium Atelier branding of EX SHARE:
- **Palette**: Sleek, moody high-fashion dark theme with glassmorphism.
  - Background: Deep Slate `#090a0f` / `#0d0f18`
  - Cards & Panels: `#121522` with subtle borders (`border-white/10` or `border-zinc-800/80`) and backdrop blur (`backdrop-blur-md`).
  - Brand Gold: `#d4af37` / `#eab308` (for revenue, luxury badges, highlights)
  - Atelier Violet: `#8b5cf6` / `#a855f7` (for users, creative metrics)
  - Emerald Green: `#10b981` (for success indicators, positive growth curves)
  - Crimson / Rose: `#f43f5e` (for failed payments, negative churn)
- **Typography**: Clean modern sans-serif (e.g. *Inter*, *Outfit*, or *Plus Jakarta Sans*) with monospace numerals for financial KPIs.
- **Charts**: Smooth bezier curves (stroke width `2.5px`), gradient fills under curves, custom dark glass tooltips with currency formatting.

---

## 6. Frontend Architecture & Component Blueprint

```
src/
├── app/
│   └── admin/
│       ├── layout.tsx            # AdminLayout with Sidebar, Topbar & Auth Guard
│       ├── page.tsx              # Overview Executive Dashboard
│       ├── users/
│       │   └── page.tsx          # Users Directory Table with filters
│       └── payments/
│           └── page.tsx          # Payments & Revenue Transaction Log
├── components/
│   └── admin/
│       ├── AdminSidebar.tsx      # Atelier Navigation sidebar with active state
│       ├── AdminTopbar.tsx       # Live status, date range selector, admin avatar
│       ├── KpiCard.tsx           # Stat card with delta trend badge & mini sparkline
│       ├── UserGrowthChart.tsx   # Dual-axis / area chart for new & cumulative users
│       ├── RevenueTrendChart.tsx # Financial bar/line chart with currency formatting
│       ├── SubscriptionsDonut.tsx# Tier breakdown interactive donut chart
│       ├── StorageUsageMeter.tsx # Storage utilization progress bar & top studios
│       ├── RecentPaymentsTable.tsx # Live payment transactions list
│       └── RecentUsersList.tsx   # Recent signups with role & status tags
├── hooks/
│   ├── useAdminOverview.ts       # TanStack Query hook for overview metrics
│   ├── useAdminUsers.ts          # Paginated query hook for users directory
│   └── useAdminPayments.ts       # Paginated query hook for transactions
└── lib/
    └── api/
        └── adminClient.ts        # Axios client with JWT interceptor & 401 handling
```

---

## 7. Component Implementation Blueprints

### 7.1. API Client & Data Fetching Hook

```typescript
// src/lib/api/adminClient.ts
import axios from 'axios';

const adminClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'https://server.exshare.ai/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

adminClient.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

adminClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 || error.response?.status === 403) {
      if (typeof window !== 'undefined') {
        window.location.href = '/login?redirect=/admin';
      }
    }
    return Promise.reject(error);
  }
);

export default adminClient;
```

```typescript
// src/hooks/useAdminOverview.ts
import { useQuery } from '@tanstack/react-query';
import adminClient from '@/lib/api/adminClient';
import { AdminDashboardOverviewResponse } from '@/types/adminDashboard';

export const useAdminOverview = (days: number = 30) => {
  return useQuery<AdminDashboardOverviewResponse>({
    queryKey: ['admin', 'dashboard', 'overview', days],
    queryFn: async () => {
      const res = await adminClient.get<AdminDashboardOverviewResponse>(
        `/admin/dashboard/overview/?days=${days}`
      );
      return res.data;
    },
    refetchInterval: 60000, // Background refresh every 60s
    staleTime: 30000,
  });
};
```

---

### 7.2. Executive Overview Page Component (`page.tsx`)

```tsx
// src/app/admin/page.tsx
'use client';

import React, { useState } from 'react';
import { 
  Users, 
  IndianRupee, 
  TrendingUp, 
  HardDrive, 
  Camera, 
  Sparkles, 
  CreditCard,
  Heart,
  ArrowUpRight,
  ArrowDownRight,
  Calendar
} from 'lucide-react';
import { useAdminOverview } from '@/hooks/useAdminOverview';
import { KpiCard } from '@/components/admin/KpiCard';
import { UserGrowthChart } from '@/components/admin/UserGrowthChart';
import { RevenueTrendChart } from '@/components/admin/RevenueTrendChart';
import { SubscriptionsDonut } from '@/components/admin/SubscriptionsDonut';
import { StorageUsageMeter } from '@/components/admin/StorageUsageMeter';
import { RecentPaymentsTable } from '@/components/admin/RecentPaymentsTable';
import { RecentUsersList } from '@/components/admin/RecentUsersList';

export default function AdminOverviewDashboard() {
  const [daysWindow, setDaysWindow] = useState<number>(30);
  const { data, isLoading, error, refetch, isFetching } = useAdminOverview(daysWindow);

  if (isLoading) {
    return (
      <div className="flex h-96 w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
          <p className="text-sm font-medium text-zinc-400">Loading Atelier Platform Intelligence...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-950/20 p-6 text-center text-rose-400">
        <p className="font-semibold">Failed to fetch platform metrics.</p>
        <button 
          onClick={() => refetch()} 
          className="mt-3 rounded-lg bg-rose-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-rose-500"
        >
          Retry Connection
        </button>
      </div>
    );
  }

  const { kpis, user_growth, revenue_analytics, subscriptions, storage, recent_payments, recent_users } = data;

  return (
    <div className="space-y-8 p-6 lg:p-8">
      {/* Header with Title and Range Picker */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-white lg:text-3xl">Executive Dashboard</h1>
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>
          <p className="mt-1 text-sm text-zinc-400">
            Real-time telemetry, revenue performance, and studio asset throughput.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/80 p-1">
          {[7, 30, 90, 365].map((d) => (
            <button
              key={d}
              onClick={() => setDaysWindow(d)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                daysWindow === d
                  ? 'bg-amber-500/20 text-amber-400 shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {d === 365 ? '1 Year' : `${d} Days`}
            </button>
          ))}
        </div>
      </div>

      {/* Primary KPI Grid (4 Columns) */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Users"
          value={kpis.total_users.toLocaleString()}
          delta={`${kpis.user_growth_percentage > 0 ? '+' : ''}${kpis.user_growth_percentage}%`}
          isPositive={kpis.user_growth_percentage >= 0}
          subtitle={`+${kpis.new_users_window} new in last ${daysWindow}d`}
          icon={<Users className="h-5 w-5 text-violet-400" />}
          gradient="from-violet-500/10 to-transparent"
        />

        <KpiCard
          title="Total Revenue"
          value={`₹${kpis.total_revenue.toLocaleString('en-IN')}`}
          delta={`${kpis.revenue_growth_percentage > 0 ? '+' : ''}${kpis.revenue_growth_percentage}%`}
          isPositive={kpis.revenue_growth_percentage >= 0}
          subtitle={`₹${kpis.revenue_window.toLocaleString('en-IN')} in last ${daysWindow}d`}
          icon={<IndianRupee className="h-5 w-5 text-amber-400" />}
          gradient="from-amber-500/10 to-transparent"
        />

        <KpiCard
          title="Monthly Recurring (MRR)"
          value={`₹${kpis.mrr.toLocaleString('en-IN')}`}
          delta={`ARR: ₹${(kpis.arr / 100000).toFixed(1)}L`}
          isPositive={true}
          subtitle={`${kpis.active_subscribers} active subscribers`}
          icon={<TrendingUp className="h-5 w-5 text-emerald-400" />}
          gradient="from-emerald-500/10 to-transparent"
        />

        <KpiCard
          title="Cloud Storage Consumed"
          value={`${kpis.total_storage_used_gb} GB`}
          delta={`${kpis.total_media_items.toLocaleString()} assets`}
          isPositive={true}
          subtitle={`${kpis.total_galleries} galleries hosted`}
          icon={<HardDrive className="h-5 w-5 text-cyan-400" />}
          gradient="from-cyan-500/10 to-transparent"
        />
      </div>

      {/* Secondary Quick Metrics Strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-4">
        <div className="flex items-center gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
          <Camera className="h-5 w-5 text-amber-400" />
          <div>
            <div className="text-xs text-zinc-400">Total Studios</div>
            <div className="text-base font-semibold text-white">{kpis.total_photographers}</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
          <Sparkles className="h-5 w-5 text-purple-400" />
          <div>
            <div className="text-xs text-zinc-400">Live Events (QR/AI)</div>
            <div className="text-base font-semibold text-white">{kpis.total_live_events}</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
          <Heart className="h-5 w-5 text-rose-400" />
          <div>
            <div className="text-xs text-zinc-400">Guest Likes & Proofs</div>
            <div className="text-base font-semibold text-white">{kpis.total_photo_likes.toLocaleString()}</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
          <CreditCard className="h-5 w-5 text-emerald-400" />
          <div>
            <div className="text-xs text-zinc-400">Avg. Order Value</div>
            <div className="text-base font-semibold text-white">₹{kpis.avg_order_value}</div>
          </div>
        </div>
      </div>

      {/* Interactive Charts: User Growth & Revenue Velocity */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6 backdrop-blur-md">
          <h2 className="text-base font-semibold text-white">User Acquisition & Growth</h2>
          <p className="text-xs text-zinc-400">Daily signups and cumulative platform members</p>
          <div className="mt-4 h-72">
            <UserGrowthChart data={user_growth.time_series} />
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6 backdrop-blur-md">
          <h2 className="text-base font-semibold text-white">Revenue Performance (INR)</h2>
          <p className="text-xs text-zinc-400">Gross subscription payments and invoice volume</p>
          <div className="mt-4 h-72">
            <RevenueTrendChart data={revenue_analytics.time_series} />
          </div>
        </div>
      </div>

      {/* Subscriptions & Storage Deep Dive */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Tier Distribution Donut */}
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6">
          <h2 className="text-base font-semibold text-white">Subscription Tiers</h2>
          <p className="text-xs text-zinc-400">Active studios grouped by tier</p>
          <div className="mt-4 h-64">
            <SubscriptionsDonut tiers={subscriptions.by_tier} />
          </div>
        </div>

        {/* Cloud Storage Leaderboard (Takes 2 cols) */}
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6 lg:col-span-2">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Cloud Storage Allocation</h2>
              <p className="text-xs text-zinc-400">Highest bandwidth & storage consuming studios</p>
            </div>
            <span className="rounded-full bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-400">
              {storage.total_gb} GB Used
            </span>
          </div>

          <div className="mt-6">
            <StorageUsageMeter 
              totalGb={storage.total_gb} 
              topStudios={storage.top_studios} 
            />
          </div>
        </div>
      </div>

      {/* Recent Activity Feeds */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6 lg:col-span-2">
          <div className="flex items-center justify-between pb-4">
            <h2 className="text-base font-semibold text-white">Recent Transactions</h2>
            <a href="/admin/payments" className="text-xs text-amber-400 hover:underline">View All</a>
          </div>
          <RecentPaymentsTable payments={recent_payments} />
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6">
          <div className="flex items-center justify-between pb-4">
            <h2 className="text-base font-semibold text-white">Recent Registrations</h2>
            <a href="/admin/users" className="text-xs text-violet-400 hover:underline">View All</a>
          </div>
          <RecentUsersList users={recent_users} />
        </div>
      </div>
    </div>
  );
}
```

---

### 7.3. KPI Card Component (`KpiCard.tsx`)

```tsx
// src/components/admin/KpiCard.tsx
import React from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface KpiCardProps {
  title: string;
  value: string;
  delta: string;
  isPositive: boolean;
  subtitle: string;
  icon: React.ReactNode;
  gradient: string;
}

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  delta,
  isPositive,
  subtitle,
  icon,
  gradient,
}) => {
  return (
    <div className={`relative overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-900/60 p-5 backdrop-blur-md transition-all hover:border-zinc-700`}>
      <div className={`absolute -right-12 -top-12 h-32 w-32 rounded-full bg-gradient-to-br ${gradient} blur-2xl`} />
      
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-zinc-400">{title}</span>
        <div className="rounded-xl border border-zinc-800 bg-zinc-800/50 p-2">{icon}</div>
      </div>

      <div className="mt-4 flex items-baseline gap-2">
        <span className="text-2xl font-bold tracking-tight text-white lg:text-3xl">{value}</span>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-zinc-800/50 pt-3 text-xs">
        <div className="flex items-center gap-1 font-medium">
          {isPositive ? (
            <span className="flex items-center text-emerald-400">
              <ArrowUpRight className="h-3.5 w-3.5" />
              {delta}
            </span>
          ) : (
            <span className="flex items-center text-rose-400">
              <ArrowDownRight className="h-3.5 w-3.5" />
              {delta}
            </span>
          )}
        </div>
        <span className="text-zinc-500">{subtitle}</span>
      </div>
    </div>
  );
};
```

---

### 7.4. Interactive User Growth Chart (`UserGrowthChart.tsx`)

```tsx
// src/components/admin/UserGrowthChart.tsx
import React from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { UserGrowthPoint } from '@/types/adminDashboard';

interface UserGrowthChartProps {
  data: UserGrowthPoint[];
}

export const UserGrowthChart: React.FC<UserGrowthChartProps> = ({ data }) => {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="userGrowthGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.4} />
            <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
        <XAxis 
          dataKey="date" 
          tickFormatter={(val) => val.slice(5)} 
          stroke="#71717a" 
          fontSize={11} 
        />
        <YAxis stroke="#71717a" fontSize={11} />
        <Tooltip
          contentStyle={{
            backgroundColor: '#18181b',
            border: '1px solid #27272a',
            borderRadius: '12px',
            color: '#f4f4f5',
            fontSize: '12px',
          }}
          labelFormatter={(label) => `Date: ${label}`}
        />
        <Area
          type="monotone"
          dataKey="cumulative_users"
          stroke="#8b5cf6"
          strokeWidth={2.5}
          fill="url(#userGrowthGrad)"
          name="Total Users"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
};
```

---

### 7.5. Revenue Trend Chart (`RevenueTrendChart.tsx`)

```tsx
// src/components/admin/RevenueTrendChart.tsx
import React from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { RevenuePoint } from '@/types/adminDashboard';

interface RevenueTrendChartProps {
  data: RevenuePoint[];
}

export const RevenueTrendChart: React.FC<RevenueTrendChartProps> = ({ data }) => {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
        <XAxis 
          dataKey="date" 
          tickFormatter={(val) => val.slice(5)} 
          stroke="#71717a" 
          fontSize={11} 
        />
        <YAxis 
          stroke="#71717a" 
          fontSize={11} 
          tickFormatter={(v) => `₹${v >= 1000 ? `${(v/1000).toFixed(0)}k` : v}`} 
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#18181b',
            border: '1px solid #27272a',
            borderRadius: '12px',
            color: '#f4f4f5',
            fontSize: '12px',
          }}
          formatter={(value: any) => [`₹${Number(value).toLocaleString('en-IN')}`, 'Revenue']}
        />
        <Bar dataKey="revenue" fill="#eab308" radius={[4, 4, 0, 0]} name="Daily Revenue" />
      </BarChart>
    </ResponsiveContainer>
  );
};
```

---

### 7.6. Recent Payments Table (`RecentPaymentsTable.tsx`)

```tsx
// src/components/admin/RecentPaymentsTable.tsx
import React from 'react';
import { AdminPaymentItem } from '@/types/adminDashboard';

interface RecentPaymentsTableProps {
  payments: AdminPaymentItem[];
}

export const RecentPaymentsTable: React.FC<RecentPaymentsTableProps> = ({ payments }) => {
  if (payments.length === 0) {
    return <div className="py-8 text-center text-xs text-zinc-500">No recent payments recorded.</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-zinc-800 text-zinc-400">
          <tr>
            <th className="pb-3 font-medium">Customer / Studio</th>
            <th className="pb-3 font-medium">Plan</th>
            <th className="pb-3 font-medium">Amount</th>
            <th className="pb-3 font-medium">Status</th>
            <th className="pb-3 font-medium">Date</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60 text-zinc-300">
          {payments.map((p) => (
            <tr key={p.id} className="hover:bg-zinc-800/30">
              <td className="py-3">
                <div className="font-medium text-white">{p.studio_name || 'Individual'}</div>
                <div className="text-[11px] text-zinc-500">{p.user_email}</div>
              </td>
              <td className="py-3">
                <span className="rounded-md bg-zinc-800 px-2 py-1 text-[11px] text-zinc-300">
                  {p.plan_name}
                </span>
              </td>
              <td className="py-3 font-mono font-medium text-amber-400">
                ₹{Number(p.amount).toLocaleString('en-IN')}
              </td>
              <td className="py-3">
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  p.status === 'success' 
                    ? 'bg-emerald-500/10 text-emerald-400' 
                    : p.status === 'failed' 
                    ? 'bg-rose-500/10 text-rose-400' 
                    : 'bg-amber-500/10 text-amber-400'
                }`}>
                  {p.status.toUpperCase()}
                </span>
              </td>
              <td className="py-3 text-zinc-500">
                {new Date(p.created_at).toLocaleDateString('en-IN', {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit'
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
```

---

### 7.7. Route Security & Access Guard (`AdminGuard.tsx`)

```tsx
// src/components/admin/AdminGuard.tsx
'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

export const AdminGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const router = useRouter();
  const [isAuthorized, setIsAuthorized] = useState<boolean>(false);

  useEffect(() => {
    const role = localStorage.getItem('user_role');
    const isStaff = localStorage.getItem('is_staff') === 'true';
    const isSuperuser = localStorage.getItem('is_superuser') === 'true';

    if (isSuperuser || isStaff || role === 'admin' || role === 'staff') {
      setIsAuthorized(true);
    } else {
      router.replace('/login?error=unauthorized_admin');
    }
  }, [router]);

  if (!isAuthorized) {
    return null;
  }

  return <>{children}</>;
};
```

---

## 8. Checklist for Frontend Deployment

1. [ ] **Environment Variable**: Set `NEXT_PUBLIC_API_URL=https://server.exshare.ai/api` in your `.env.local`.
2. [ ] **Install Packages**: Install `recharts` (or `@tremor/react`), `lucide-react`, and `@tanstack/react-query`.
3. [ ] **CORS Verification**: Backend allows credentials and origins from `app.exshare.ai`, `localhost:3000`, etc.
4. [ ] **Authentication**: Include `Authorization: Bearer <jwt_access_token>` in all requests.
5. [ ] **Polite Refresh**: Default polling is set to 60s for overview metrics to prevent excessive database I/O while maintaining live telemetry.
