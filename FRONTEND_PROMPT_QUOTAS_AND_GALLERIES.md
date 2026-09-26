# Frontend Integration Prompt: Connect Studio Plan Quotas & Client Galleries Status/Filtering

> **Target Stack:** React 19 + TypeScript + Vite + TanStack Query v5 + Axios  
> **API Base URL:** `http://localhost:8000/api` (with `withCredentials: true`)  
> **Scope:** Connect the recent Django REST Framework updates for:
> 1. **Studio Plan Quotas & Real-Time Aggregated Usage** (`GET /api/plans/` and `GET /api/plans/current/`)
> 2. **Client Gallery Status Switching** (`active` ⇄ `delivered` via `PATCH /api/galleries/{id}/`)
> 3. **100% Server-Side Filtering & Sorting** (`GET /api/galleries/`)
> 4. **Plan Quota Interception & Upgrade Modal** (`POST /api/galleries/` 403 error handling)

---

## 1. Domain Types (`src/types/atelier.ts`)

Update or append the following TypeScript interfaces:

```typescript
export type GalleryStatus = 'active' | 'delivered' | 'draft' | 'archived';
export type GalleryTemplateId = 'editorial' | 'masonry' | 'cinematic' | 'minimal';

export interface UsageQuotaMetric {
  used: number;
  limit: number;
  remaining: number | null; // null if is_unlimited is true
  is_unlimited: boolean;
}

export interface StudioPlan {
  id: string; // 'plan-standard-3m' | 'plan-standard-1y' | 'plan-premium-elite'
  name: string;
  subtitle: string;
  tier: 'standard' | 'premium' | 'custom';
  billing_cycle: 'quarterly' | 'annual' | 'monthly';
  monthly_price: number | string;
  total_price: number | string;
  currency: string;
  image_storage_gb: number;
  video_storage_gb: number;
  storage_limit_bytes: number;
  max_galleries: number; // 15 (3M), 50 (1Y), 0 (unlimited)
  gallery_expiry_days: number; // 90 (3M), 365 (1Y), 0 (permanent)
  face_search_enabled: boolean; // false on Standard 3M, true on 1Y & Premium
  allowed_templates: GalleryTemplateId[]; // ['editorial', 'masonry'] or all 4
  max_events: number; // 5 (3M), 25 (1Y), 0 (unlimited)
  max_portfolio_posts: number; // 10 (3M), 30 (1Y), 0 (unlimited)
  has_full_inquiry_access: boolean;
  inquiry_access: string;
}

export interface CurrentSubscription {
  id: string;
  status: 'active' | 'expired' | 'pending' | 'cancelled';
  plan: StudioPlan;
  billing_cycle: string;
  current_period_start: string;
  current_period_end: string;
  days_remaining: number;
  is_active: boolean;
  effective_storage_limit_bytes: number;
  storage_limit_gb: number;
  usage: {
    storage: {
      used_bytes: number;
      limit_bytes: number;
      remaining_bytes: number;
      used_gb: number;
      limit_gb: number;
      percent_used: number;
      is_unlimited: boolean;
    };
    galleries: UsageQuotaMetric;
    events: UsageQuotaMetric;
    portfolio_posts: UsageQuotaMetric;
  };
  auto_renew: boolean;
}

export interface Gallery {
  id: string;
  slug: string;
  title: string;
  client_name: string;
  client_email?: string;
  event_date: string;
  status: GalleryStatus;
  template_id: GalleryTemplateId;
  cover_image?: string;
  cover_image_url?: string;
  is_password_protected: boolean;
  allow_downloads: boolean;
  allow_favorites: boolean;
  face_search_enabled: boolean;
  views_count: number;
  photos_count: number;
  share_url?: string;
  created_at: string;
  updated_at: string;
}

export interface GalleryFilterParams {
  search?: string;
  status?: 'active' | 'delivered';
  date_filter?: 'this-year' | 'last-year' | 'last-30-days' | 'last-3-months' | 'last-6-months' | 'custom' | string;
  date_from?: string; // YYYY-MM-DD
  date_to?: string;   // YYYY-MM-DD
  sort?: 'date-desc' | 'date-asc' | 'name' | 'photos';
}
```

---

## 2. API Service Layer

### 2.1 Studio Plans Service (`src/service/plans/PlanApi.ts`)
```typescript
import { axiosInstance } from '@/lib/axiosInstance';
import type { StudioPlan, CurrentSubscription } from '@/types/atelier';

/** Get all available studio tiers with feature limits */
export const GetStudioPlansApi = async (): Promise<StudioPlan[]> => {
  const res = await axiosInstance.get<StudioPlan[]>('/plans/');
  return res.data;
};

/** Get current active plan with real-time aggregated usage metrics */
export const GetCurrentSubscriptionApi = async (): Promise<CurrentSubscription> => {
  const res = await axiosInstance.get<CurrentSubscription>('/plans/current/');
  return res.data;
};
```

### 2.2 Client Galleries Service (`src/service/galleries/GalleryApi.ts`)
```typescript
import { axiosInstance } from '@/lib/axiosInstance';
import type { Gallery, GalleryFilterParams } from '@/types/atelier';

/** Server-side filtered and sorted gallery listing */
export const GetGalleriesApi = async (params?: GalleryFilterParams): Promise<Gallery[]> => {
  const res = await axiosInstance.get<Gallery[]>('/galleries/', { params });
  return res.data;
};

/** Create gallery with quota and template validation */
export const CreateGalleryApi = async (payload: {
  title: string;
  client_name?: string;
  client_email?: string;
  event_date?: string;
  template_id?: string;
}): Promise<Gallery> => {
  const res = await axiosInstance.post<Gallery>('/galleries/', payload);
  return res.data;
};

/** Fast status toggle: 'active' ⇄ 'delivered' */
export const UpdateGalleryStatusApi = async (
  galleryId: string,
  status: 'active' | 'delivered'
): Promise<Gallery> => {
  const res = await axiosInstance.patch<Gallery>(`/galleries/${galleryId}/`, { status });
  return res.data;
};

/** Move gallery to archive */
export const DeleteGalleryApi = async (galleryId: string): Promise<void> => {
  await axiosInstance.delete(`/galleries/${galleryId}/`);
};
```

---

## 3. TanStack Query Hooks with Optimistic Status Updates

### 3.1 Gallery Hooks (`src/hooks/useGalleries.ts`)
```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { GetGalleriesApi, UpdateGalleryStatusApi, CreateGalleryApi } from '@/service/galleries/GalleryApi';
import type { Gallery, GalleryFilterParams } from '@/types/atelier';

export const useGalleries = (filters: GalleryFilterParams) => {
  return useQuery({
    queryKey: ['galleries', filters],
    queryFn: () => GetGalleriesApi(filters),
    placeholderData: (prev) => prev, // Keeps current UI while background fetching new query params
    staleTime: 1000 * 30,
  });
};

export const useUpdateGalleryStatus = (currentFilters: GalleryFilterParams) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ galleryId, status }: { galleryId: string; status: 'active' | 'delivered' }) =>
      UpdateGalleryStatusApi(galleryId, status),
    onMutate: async ({ galleryId, status }) => {
      await queryClient.cancelQueries({ queryKey: ['galleries', currentFilters] });
      const previous = queryClient.getQueryData<Gallery[]>(['galleries', currentFilters]);

      // Optimistically update the status badge
      if (previous) {
        queryClient.setQueryData<Gallery[]>(
          ['galleries', currentFilters],
          previous.map((g) => (g.id === galleryId ? { ...g, status } : g))
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['galleries', currentFilters], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['galleries'] });
      queryClient.invalidateQueries({ queryKey: ['current-subscription'] });
    },
  });
};
```

### 3.2 Subscription Usage Hook (`src/hooks/useSubscription.ts`)
```typescript
import { useQuery } from '@tanstack/react-query';
import { GetCurrentSubscriptionApi } from '@/service/plans/PlanApi';

export const useCurrentSubscription = () => {
  return useQuery({
    queryKey: ['current-subscription'],
    queryFn: GetCurrentSubscriptionApi,
    staleTime: 1000 * 60 * 2,
  });
};
```

---

## 4. UI Component Wiring

### 4.1 Filter & Sorting Bar on Galleries Page (`src/pages/GalleriesPage.tsx`)
Connect the toolbar state to `GalleryFilterParams`:
- **Search Bar**: Debounce input by 300ms → `filters.search`.
- **Status Tabs**:
  - `All`: `status: undefined`
  - `Active`: `status: 'active'`
  - `Delivered`: `status: 'delivered'`
- **Date Presets Dropdown**:
  - `this-year` (This Year)
  - `last-year` (Last Year)
  - `last-30-days` (Last 30 Days)
  - `last-3-months` (Last 3 Months)
  - `last-6-months` (Last 6 Months)
  - `custom` (Displays `date_from` and `date_to` date pickers)
- **Sort Dropdown**:
  - `date-desc`: "Newest Event Date"
  - `date-asc`: "Oldest Event Date"
  - `name`: "Gallery Name (A-Z)"
  - `photos`: "Photo Count (High to Low)"

### 4.2 Status Toggle Button on Gallery Cards (`src/components/GalleryStatusToggle.tsx`)
```tsx
import React from 'react';
import { useUpdateGalleryStatus } from '@/hooks/useGalleries';
import type { GalleryFilterParams } from '@/types/atelier';

interface Props {
  galleryId: string;
  currentStatus: 'active' | 'delivered';
  filters: GalleryFilterParams;
}

export const GalleryStatusToggle: React.FC<Props> = ({ galleryId, currentStatus, filters }) => {
  const mutation = useUpdateGalleryStatus(filters);
  const isDelivered = currentStatus === 'delivered';

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    const nextStatus = isDelivered ? 'active' : 'delivered';
    mutation.mutate({ galleryId, status: nextStatus });
  };

  return (
    <button
      onClick={handleToggle}
      disabled={mutation.isPending}
      className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
        isDelivered
          ? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
          : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
      }`}
    >
      {mutation.isPending ? 'Updating...' : isDelivered ? 'Delivered' : 'Active'}
    </button>
  );
};
```

### 4.3 Create Gallery Quota Guard & 403 Handler (`src/components/CreateGalleryModal.tsx`)
- Read `subscription.usage.galleries`:
  ```tsx
  const { data: subscription } = useCurrentSubscription();
  const galleryQuota = subscription?.usage.galleries;
  const isLimitReached = galleryQuota && !galleryQuota.is_unlimited && galleryQuota.remaining === 0;
  ```
- If `isLimitReached`:
  - Show warning banner: `"Gallery quota reached (${galleryQuota.used}/${galleryQuota.limit}). Upgrade your plan to create more client galleries."`
  - Replace Submit button with an `"Upgrade Plan"` button that opens the Plan Upgrade modal.
- In `CreateGalleryApi` error handler:
  ```typescript
  onError: (error: any) => {
    const errorData = error.response?.data;
    if (errorData?.code === 'GALLERY_LIMIT_EXCEEDED' || errorData?.upgrade_required) {
      toast.error(errorData.message || 'Gallery quota exceeded. Please upgrade.');
      setIsUpgradeModalOpen(true);
    } else if (errorData?.code === 'TEMPLATE_NOT_ALLOWED') {
      toast.error(errorData.detail || 'This template is locked on your current plan.');
      setIsUpgradeModalOpen(true);
    } else {
      toast.error('Failed to create gallery.');
    }
  }
  ```

### 4.4 Dashboard Real-Time Quota Widget (`src/components/StudioQuotaWidget.tsx`)
Render the progress bars using `subscription.usage`:
- **Galleries Progress**:
  `{usage.galleries.used} / {usage.galleries.is_unlimited ? '∞' : usage.galleries.limit} Galleries`
- **Storage Progress**:
  `{usage.storage.used_gb} GB / {usage.storage.limit_gb} GB ({usage.storage.percent_used}%)`
- **Events Progress**:
  `{usage.events.used} / {usage.events.is_unlimited ? '∞' : usage.events.limit} Events`
- **Inquiry Access Badge**:
  `{subscription.plan.inquiry_access}` (e.g. `"All Inquiries"` vs `"Random 10 Inquiries"`)
