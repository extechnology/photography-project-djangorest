# EX SHARE Atelier — Frontend Integration & Connection Implementation Guide
## Architecture: React 19 + TypeScript + Vite + TanStack Query + Axios

> **Document Version:** 2.0.0  
> **Target Frontend Stack:** React 19, TypeScript 5+, Vite, TanStack Query v5+, Axios (`axiosInstance.ts`), TailwindCSS  
> **Backend Stack:** Django 5.1+, Django REST Framework, Celery, Redis, PostgreSQL (pgvector)  
> **API Base URL:** `http://localhost:8000/api` (or DevTunnel: `https://<tunnel-id>.devtunnels.ms/api`)

---

## Table of Contents

1. [Network Configuration & Axios Instance](#1-network-configuration--axios-instance)
2. [Complete TypeScript Domain Models & Types](#2-complete-typescript-domain-models--types)
3. [Complete 1:1 API Client Services](#3-complete-11-api-client-services)
   - [3.1 Authentication & Passwordless OTP (`AuthApi.ts`)](#31-authentication--passwordless-otp-authapits)
   - [3.2 Photographer Profile & Onboarding (`ProfileApi.ts`)](#32-photographer-profile--onboarding-profileapits)
   - [3.3 Studio Plans, Subscriptions & Razorpay (`PlanApi.ts`)](#33-studio-plans-subscriptions--razorpay-planapits)
   - [3.4 Client Galleries & Cloud Drive (`GalleryApi.ts`)](#34-client-galleries--cloud-drive-galleryapits)
   - [3.5 Public Client Gallery Experience (`PublicGalleryApi.ts`)](#35-public-client-gallery-experience-publicgalleryapits)
   - [3.6 Live Events, Camera Tethering & Guest QR (`EventApi.ts`)](#36-live-events-camera-tethering--guest-qr-eventapits)
   - [3.7 AI Biometric Face Search (`FaceSearchApi.ts`)](#37-ai-biometric-face-search-facesearchapits)
   - [3.8 Client Inquiries & Lead Pipeline (`InquiryApi.ts`)](#38-client-inquiries--lead-pipeline-inquiryapits)
   - [3.9 Photographer Portfolio Studio (`PortfolioApi.ts`)](#39-photographer-portfolio-studio-portfolioapits)
   - [3.10 Gallery Analytics & Activity Telemetry (`AnalyticsApi.ts`)](#310-gallery-analytics--activity-telemetry-analyticsapits)
   - [3.11 Soundtrack & Audio Library (`MusicApi.ts`)](#311-soundtrack--audio-library-musicapits)
4. [TanStack React Query Hooks Collection](#4-tanstack-react-query-hooks-collection)
5. [Plan Enforcement, Quota Guards & Upgrade Modals](#5-plan-enforcement-quota-guards--upgrade-modals)
6. [Component 1:1 Wiring Examples](#6-component-11-wiring-examples)
   - [6.1 Move Live Event to Gallery Drive (`MoveToGalleryModal.tsx`)](#61-move-live-event-to-gallery-drive-movetogallerymodaltsx)
   - [6.2 Move Photos to Another Section / Title (`GalleryDetailPage.tsx`)](#62-move-photos-to-another-section--title-gallerydetailpagetsx)
   - [6.3 Share Links, Expiration & QR Code (`ShareModal.tsx`)](#63-share-links-expiration--qr-code-sharemodaltsx)
   - [6.4 AI Face Search (`AIFaceSearchBox.tsx`)](#64-ai-face-search-aifacesearchboxtsx)
   - [6.5 Inquiries Masking UI (`InquiriesPage.tsx`)](#65-inquiries-masking-ui-inquiriespagetsx)
   - [6.6 Watermark & Settings Suite (`SettingsPage.tsx`)](#66-watermark--settings-suite-settingspagetsx)

---

## 1. Network Configuration & Axios Instance

The frontend communicates with the Django REST backend via an Axios client configured for **HTTP-only cookie-based authentication** (`withCredentials: true`) with automatic Authorization Bearer fallback.

### 1.1 `.env` Configuration
```env
# Local Development
VITE_API_BASE_URL=http://localhost:8000/api

# Or via Cloudflare / VS Code DevTunnel:
# VITE_API_BASE_URL=https://r2jsm33h-8000.inc1.devtunnels.ms/api
```

### 1.2 `src/lib/axiosInstance.ts`
```typescript
import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

export const axiosInstance = axios.create({
  baseURL,
  withCredentials: true, // Crucial for HTTP-only JWT cookies (access_token, refresh_token)
  headers: {
    'Accept': 'application/json',
  },
  timeout: 45000, // 45s for high-res uploads
});

// Request Interceptor: Append Bearer token if stored in memory/localStorage (optional fallback)
axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('token');
    if (token && !config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response Interceptor: Seamless Token Refresh on 401
let isRefreshing = false;
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: any) => void }> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token!);
    }
  });
  failedQueue = [];
};

axiosInstance.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Handle 401 Unauthorized (Token Expired)
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (originalRequest.url?.includes('/auth/passwordless/') || originalRequest.url?.includes('/auth/check-login/')) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            if (token) originalRequest.headers.Authorization = `Bearer ${token}`;
            return axiosInstance(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const refreshResponse = await axios.post(
          `${baseURL}/auth/token/refresh/`,
          {},
          { withCredentials: true }
        );
        const newToken = refreshResponse.data?.access;
        if (newToken) {
          localStorage.setItem('token', newToken);
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
        }
        processQueue(null, newToken);
        return axiosInstance(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        localStorage.removeItem('token');
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);
```

### 1.3 `src/lib/CommonApi.ts`
```typescript
import { axiosInstance } from './axiosInstance';
import type { AxiosRequestConfig, Method } from 'axios';

export const CommonApi = async <T = any>(
  method: Method,
  url: string,
  data?: any,
  config?: AxiosRequestConfig
): Promise<T> => {
  const isFormData = data instanceof FormData;
  const headers = {
    ...(config?.headers || {}),
    ...(isFormData ? { 'Content-Type': 'multipart/form-data' } : { 'Content-Type': 'application/json' }),
  };

  const response = await axiosInstance({
    method,
    url,
    data: method !== 'GET' ? data : undefined,
    params: method === 'GET' ? data : config?.params,
    ...config,
    headers,
  });

  return response.data as T;
};
```

---

## 2. Complete TypeScript Domain Models & Types

Save to `src/types/atelier.ts`:

```typescript
export type PlanTier = 'standard' | 'premium' | 'custom';
export type BillingCycle = 'quarterly' | 'annual' | 'monthly';
export type GalleryTemplateId = 'editorial' | 'masonry' | 'cinematic' | 'minimal';
export type GalleryStatus = 'active' | 'delivered' | 'draft' | 'archived';
export type MediaType = 'photo' | 'video';
export type InquiryStatus = 'new' | 'contacted' | 'booked' | 'archived';

// ---------------------------------------------------------------------------
// Studio Plans & Subscriptions
// ---------------------------------------------------------------------------
export interface StudioPlan {
  id: string; // 'plan-standard-3m' | 'plan-standard-1y' | 'plan-premium-elite'
  name: string;
  subtitle: string;
  tier: PlanTier;
  billing_cycle: BillingCycle;
  period_label: string;
  duration_months: number;
  monthly_price: number | string;
  original_monthly_price?: number | string | null;
  total_price: number | string;
  billing_text: string;
  currency: string;
  image_storage_gb: number;
  video_storage_gb: number;
  image_storage: string;
  video_storage: string;
  storage_limit_bytes: number;
  tag: string;
  tag_type: 'default' | 'popular' | 'current';
  cta_text: string;
  features: string[];
  max_galleries: number; // 0 = unlimited
  gallery_expiry_days: number; // 0 = permanent
  face_search_enabled: boolean;
  max_events: number;
  allowed_templates: GalleryTemplateId[];
  allowed_portfolio_templates: string[];
  max_portfolio_posts: number;
  max_inquiries: number;
  has_full_inquiry_access: boolean;
  can_upgrade_storage: boolean;
  max_upgrade_image_gb: number;
  is_active: boolean;
  sort_order: number;
}

export interface CurrentSubscription {
  id: string;
  status: 'active' | 'expired' | 'pending' | 'cancelled';
  plan: {
    id: string;
    name: string;
    tier: PlanTier;
    billing_cycle: BillingCycle;
    duration_months: number;
    total_price: string;
    currency: string;
  };
  start_date: string;
  expiry_date: string;
  days_remaining: number;
  storage: {
    used_bytes: number;
    limit_bytes: number;
    used_gb: number;
    limit_gb: number;
    used_percentage: number;
  };
  auto_renew: boolean;
  payment_gateway_ref: string;
}

// ---------------------------------------------------------------------------
// Photographer Profile & Studio Branding
// ---------------------------------------------------------------------------
export interface PhotographerProfile {
  id: number;
  name: string;
  phone: string;
  email: string;
  occupation: string;
  studio_name: string;
  bio: string;
  location: string;
  website_url?: string | null;
  instagram_handle: string;
  avatar_url?: string | null;
  default_template: GalleryTemplateId;
  enable_watermark: boolean;
  watermark_text: string;
  watermark_opacity: number;
  watermark_position: 'bottom-right' | 'bottom-left' | 'top-right' | 'center' | 'tiled';
  is_onboarded: boolean;
  onboarding_step: number;
  storage_used_bytes: number;
  storage_limit_bytes: number;
  storage_remaining_bytes: number;
  quick_info: {
    member_since: string;
    galleries_created: number;
    total_photos: number;
    total_videos: number;
    storage_used_formatted: string;
    storage_limit_formatted: string;
    storage_display: string;
  };
  plan_details?: {
    name: string;
    tier: string;
    billing_cycle: string;
    headline: string;
    description: string;
  };
}

// ---------------------------------------------------------------------------
// Client Gallery & Media
// ---------------------------------------------------------------------------
export interface GallerySection {
  id?: number;
  title: string;
  order: number;
  count?: number;
}

export interface MediaItem {
  id: string;
  gallery: string;
  section_title?: string;
  type: MediaType;
  file_url: string;
  thumbnail_url?: string | null;
  preview_url?: string | null;
  title?: string;
  caption?: string;
  original_filename: string;
  aspect_ratio: number;
  width?: number;
  height?: number;
  file_size: number;
  is_cover: boolean;
  is_favorite: boolean;
  duration?: string;
  video_embed_url?: string;
  sort_order: number;
  created_at: string;
}

export interface Gallery {
  id: string;
  slug: string;
  title: string;
  client_name: string;
  client_email?: string;
  event_date: string;
  cover_image?: string;
  template_id: GalleryTemplateId;
  template_banners?: Record<string, string>;
  masonry_banner_images?: string[];
  status: GalleryStatus;
  is_password_protected: boolean;
  allow_downloads: boolean;
  allow_favorites: boolean;
  expires_at: string | null;
  views_count: number;
  downloads_count: number;
  favorites_count: number;
  photos_count: number;
  share_token?: string;
  share_url?: string;
  sections?: GallerySection[];
  media?: MediaItem[];
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Live Events & Tethering
// ---------------------------------------------------------------------------
export interface LiveEvent {
  id: string;
  slug: string;
  title: string;
  event_type: string;
  venue: string;
  client_name?: string;
  event_date: string;
  status: 'live' | 'upcoming' | 'completed' | 'moved_to_gallery';
  auto_sync_enabled: boolean;
  tether_count: number;
  guest_views: number;
  qr_scans: number;
  ai_searches: number;
  matches_found: number;
  downloads_count: number;
  qr_settings: {
    duration_hours: number | string;
    expires_at: string;
    pin_code?: string;
    is_active: boolean;
    allow_guest_uploads: boolean;
  };
  associated_gallery_id?: string | null;
  media?: MediaItem[];
  created_at: string;
}

// ---------------------------------------------------------------------------
// Client Inquiries
// ---------------------------------------------------------------------------
export interface PortfolioInquiry {
  id: string;
  clientName: string;
  clientEmail: string;
  clientPhone: string;
  eventType: string;
  eventDate: string;
  location: string;
  budget: string;
  message: string;
  status: InquiryStatus;
  notes?: string;
  createdAt: string;
  is_locked?: boolean;
}

// ---------------------------------------------------------------------------
// Plan Enforcement Error Structure
// ---------------------------------------------------------------------------
export interface PlanEnforcementError {
  error_code:
    | 'NO_ACTIVE_SUBSCRIPTION'
    | 'GALLERY_LIMIT_EXCEEDED'
    | 'TEMPLATE_TIER_LOCKED'
    | 'FACE_SEARCH_LOCKED'
    | 'EVENT_LIMIT_EXCEEDED'
    | 'STORAGE_LIMIT_EXCEEDED'
    | 'STORAGE_UPGRADE_LIMIT_EXCEEDED';
  message: string;
  upgrade_required: boolean;
}
```

---

## 3. Complete 1:1 API Client Services

### 3.1 Authentication & Passwordless OTP (`AuthApi.ts`)
Save to `src/service/auth/AuthApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';

export const SendLoginOtpApi = async (email: string) => {
  return CommonApi('POST', '/auth/passwordless/login/send-otp/', { email });
};

export const VerifyLoginOtpApi = async (email: string, otp: string) => {
  return CommonApi('POST', '/auth/passwordless/login/verify-otp/', { email, otp });
};

export const SendRegisterOtpApi = async (email: string) => {
  return CommonApi('POST', '/auth/passwordless/reg/send-otp/', { email });
};

export const VerifyRegisterOtpApi = async (payload: {
  email: string;
  otp: string;
  fullname: string;
  role?: string;
  phone?: string;
}) => {
  return CommonApi('POST', '/auth/passwordless/reg/verify-otp/', payload);
};

export const CheckLoginStatusApi = async () => {
  return CommonApi<{ is_logged_in: boolean; user?: any }>('GET', '/auth/check-login/');
};

export const LogoutApi = async () => {
  return CommonApi('POST', '/auth/logout/', {});
};
```

---

### 3.2 Photographer Profile & Onboarding (`ProfileApi.ts`)
Save to `src/service/profile/ProfileApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';
import type { PhotographerProfile } from '@/types/atelier';

export const GetMyProfileApi = async (): Promise<PhotographerProfile> => {
  return CommonApi<PhotographerProfile>('GET', '/photographers/profiles/me/');
};

export const UpdateMyProfileApi = async (payload: Partial<PhotographerProfile>): Promise<PhotographerProfile> => {
  return CommonApi<PhotographerProfile>('PATCH', '/photographers/profiles/me/', payload);
};

export const UploadAvatarApi = async (file: File): Promise<{ avatar_url: string; profile: PhotographerProfile }> => {
  const formData = new FormData();
  formData.append('avatar', file);
  return CommonApi('POST', '/photographers/profiles/me/avatar/', formData);
};

export const DeleteAvatarApi = async (): Promise<{ message: string }> => {
  return CommonApi('DELETE', '/photographers/profiles/me/avatar/');
};

export const GetOnboardingStateApi = async (): Promise<{ is_onboarded: boolean; onboarding_step: number }> => {
  return CommonApi('GET', '/photographers/onboarding/');
};

export const CompleteOnboardingApi = async (data: FormData | Record<string, any>) => {
  return CommonApi('POST', '/photographers/onboarding/', data);
};

export const UpdateWatermarkApi = async (payload: {
  enable_watermark?: boolean;
  watermark_text?: string;
  watermark_opacity?: number;
  watermark_position?: string;
  watermark_image?: File;
}) => {
  if (payload.watermark_image instanceof File) {
    const formData = new FormData();
    Object.entries(payload).forEach(([k, v]) => {
      if (v !== undefined) formData.append(k, v as any);
    });
    return CommonApi('PATCH', '/photographers/profiles/me/watermark/', formData);
  }
  return CommonApi('PATCH', '/photographers/profiles/me/watermark/', payload);
};
```

---

### 3.3 Studio Plans, Subscriptions & Razorpay (`PlanApi.ts`)
Save to `src/service/plans/PlanApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';
import type { StudioPlan, CurrentSubscription } from '@/types/atelier';

export const GetStudioPlansApi = async (): Promise<StudioPlan[]> => {
  return CommonApi<StudioPlan[]>('GET', '/plans/');
};

export const GetCurrentSubscriptionApi = async (): Promise<CurrentSubscription> => {
  return CommonApi<CurrentSubscription>('GET', '/plans/current/');
};

export const CheckoutPlanApi = async (payload: {
  plan_id: string;
  gateway?: 'direct' | 'razorpay';
}): Promise<{
  status: string;
  direct_activated?: boolean;
  order_id?: string;
  amount_paise?: number;
  currency?: string;
  key_id?: string;
  plan_id: string;
  subscription?: CurrentSubscription;
}> => {
  return CommonApi('POST', '/plans/checkout/', payload);
};

export const VerifyPaymentApi = async (payload: {
  plan_id: string;
  gateway_order_id: string;
  gateway_payment_id: string;
  gateway_signature: string;
}): Promise<{ status: string; message: string; subscription: CurrentSubscription }> => {
  return CommonApi('POST', '/plans/verify/', payload);
};

export const CancelAutoRenewApi = async (): Promise<{ status: string; auto_renew: boolean }> => {
  return CommonApi('POST', '/plans/cancel/', {});
};

export const AddStorageAddonApi = async (additional_gb: number): Promise<{ status: string; subscription: CurrentSubscription }> => {
  return CommonApi('POST', '/plans/storage-addon/', { additional_gb });
};
```

---

### 3.4 Client Galleries & Cloud Drive (`GalleryApi.ts`)
Save to `src/service/galleries/GalleryApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';
import type { Gallery, MediaItem, GalleryTemplateId } from '@/types/atelier';

export const GetGalleriesApi = async (params?: {
  search?: string;
  status?: string;
  date_filter?: string;
}): Promise<Gallery[]> => {
  return CommonApi<Gallery[]>('GET', '/galleries/', params);
};

export const CreateGalleryApi = async (payload: {
  title: string;
  client_name?: string;
  client_email?: string;
  event_date?: string;
  description?: string;
  template_id?: GalleryTemplateId;
  visibility?: 'public' | 'private' | 'password_protected';
  password?: string;
  allow_downloads?: boolean;
  allow_favorites?: boolean;
  face_search_enabled?: boolean;
}): Promise<Gallery> => {
  return CommonApi<Gallery>('POST', '/galleries/', payload);
};

export const GetGalleryDetailApi = async (idOrSlug: string): Promise<Gallery> => {
  return CommonApi<Gallery>('GET', `/galleries/${idOrSlug}/`);
};

export const UpdateGalleryApi = async (id: string, updates: Partial<Gallery>): Promise<Gallery> => {
  return CommonApi<Gallery>('PATCH', `/galleries/${id}/`, updates);
};

export const DeleteGalleryApi = async (id: string): Promise<{ success: boolean; message: string }> => {
  return CommonApi('DELETE', `/galleries/${id}/`);
};

/** Moving Photos into Another Title / Section */
export const MoveMediaToSectionApi = async (
  galleryId: string,
  mediaIds: string[],
  targetSection: string
): Promise<{ status: string; updated_count: number; section: string }> => {
  return CommonApi('POST', `/galleries/${galleryId}/media/move-section/`, {
    media_ids: mediaIds,
    target_section: targetSection,
  });
};

/** Direct Multipart Media Upload */
export const UploadGalleryMediaApi = async (
  galleryId: string,
  file: File,
  sectionTitle?: string,
  type: 'photo' | 'video' = 'photo'
): Promise<MediaItem> => {
  const formData = new FormData();
  formData.append('photos', file);
  if (sectionTitle) formData.append('section_title', sectionTitle);
  formData.append('type', type);
  const res = await CommonApi<{ media: MediaItem[] }>('POST', `/galleries/${galleryId}/upload/`, formData);
  return res.media[0];
};

/** Batch Upload Multiple Photos */
export const BulkUploadGalleryMediaApi = async (
  galleryId: string,
  files: File[],
  sectionTitle?: string
): Promise<{ media: MediaItem[]; total_uploaded: number }> => {
  const formData = new FormData();
  files.forEach((f) => formData.append('photos', f));
  if (sectionTitle) formData.append('section_title', sectionTitle);
  return CommonApi('POST', `/galleries/${galleryId}/upload/`, formData);
};

export const DeleteGalleryMediaApi = async (mediaId: string): Promise<{ success: boolean }> => {
  return CommonApi('DELETE', `/galleries/media/${mediaId}/`);
};

export const BulkDeleteGalleryMediaApi = async (mediaIds: string[]): Promise<{ deleted_count: number; freed_bytes: number }> => {
  return CommonApi('POST', '/galleries/media/bulk-delete/', { media_ids: mediaIds });
};

export const ToggleMediaFavoriteApi = async (mediaId: string): Promise<{ is_favorite: boolean }> => {
  return CommonApi('POST', `/galleries/media/${mediaId}/favorite/`);
};

export const SetGalleryCoverImageApi = async (galleryId: string, mediaId: string): Promise<{ cover_image: string }> => {
  return CommonApi('POST', `/galleries/${galleryId}/set-cover/`, { media_id: mediaId });
};

export const SetMasonrySlotBannerApi = async (
  galleryId: string,
  slotIndex: number,
  mediaUrl: string
): Promise<{ masonry_banner_images: string[] }> => {
  return CommonApi('POST', `/galleries/${galleryId}/banners/masonry-slot/`, {
    slot_index: slotIndex,
    media_url: mediaUrl,
  });
};
```

---

### 3.5 Public Client Gallery Experience (`PublicGalleryApi.ts`)
Save to `src/service/galleries/PublicGalleryApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';
import type { Gallery } from '@/types/atelier';

export const GetPublicGalleryApi = async (slugOrId: string): Promise<Gallery> => {
  return CommonApi<Gallery>('GET', `/public/galleries/${slugOrId}/`);
};

export const VerifyGalleryPinApi = async (slugOrId: string, pin: string): Promise<{ status: string; gallery: Gallery }> => {
  return CommonApi('POST', `/public/galleries/${slugOrId}/verify-pin/`, { pin });
};

export const TrackGalleryViewApi = async (slugOrId: string, device: 'desktop' | 'mobile' | 'tablet' = 'desktop') => {
  return CommonApi('POST', `/public/galleries/${slugOrId}/track-view/`, { device });
};
```

---

### 3.6 Live Events, Camera Tethering & Guest QR (`EventApi.ts`)
Save to `src/service/events/EventApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';
import type { LiveEvent, Gallery, MediaItem } from '@/types/atelier';

export const GetEventsApi = async (): Promise<LiveEvent[]> => {
  return CommonApi<LiveEvent[]>('GET', '/events/');
};

export const CreateEventApi = async (payload: {
  title: string;
  event_type: string;
  venue?: string;
  qr_duration_hours?: number;
}): Promise<LiveEvent> => {
  return CommonApi<LiveEvent>('POST', '/events/', payload);
};

export const GetEventDetailApi = async (idOrSlug: string): Promise<LiveEvent> => {
  return CommonApi<LiveEvent>('GET', `/events/${idOrSlug}/`);
};

export const UpdateEventQRExpiryApi = async (
  eventId: string,
  durationHours: number | 'custom',
  expiresAt: string,
  pinCode?: string
): Promise<{ status: string; qr_settings: any }> => {
  return CommonApi('POST', `/events/${eventId}/qr-settings/`, {
    duration_hours: durationHours,
    expires_at: expiresAt,
    pin_code: pinCode,
  });
};

/** Move Event to Gallery Drive */
export const MoveEventToGalleryApi = async (
  eventId: string,
  payload: {
    target_mode: 'new' | 'existing';
    target_gallery_id?: string | null;
    new_gallery_title?: string;
    category_assignments: Record<string, string>; // mediaId -> Section Title
  }
): Promise<Gallery> => {
  return CommonApi<Gallery>('POST', `/events/${eventId}/move-to-gallery/`, payload);
};
```

---

### 3.7 AI Biometric Face Search (`FaceSearchApi.ts`)
Save to `src/service/ai/FaceSearchApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';

export interface FaceSearchResult {
  matched_media_ids: string[];
  total_matches: number;
  confidence: number;
}

export const SearchGalleryByFaceApi = async (
  galleryId: string,
  selfieFile: File | Blob
): Promise<FaceSearchResult> => {
  const formData = new FormData();
  formData.append('selfie', selfieFile);
  return CommonApi<FaceSearchResult>('POST', `/galleries/${galleryId}/face-search/`, formData);
};

export const SearchEventByFaceApi = async (
  eventId: string,
  selfieFile: File | Blob
): Promise<FaceSearchResult> => {
  const formData = new FormData();
  formData.append('selfie', selfieFile);
  return CommonApi<FaceSearchResult>('POST', `/events/${eventId}/face-search/`, formData);
};
```

---

### 3.8 Client Inquiries & Lead Pipeline (`InquiryApi.ts`)
Save to `src/service/inquiries/InquiryApi.ts`:

```typescript
import { CommonApi } from '@/lib/CommonApi';
import type { PortfolioInquiry, InquiryStatus } from '@/types/atelier';

export const GetInquiriesApi = async (): Promise<{
  total_inquiries: number;
  accessible_inquiries: number;
  has_full_inquiry_access: boolean;
  upgrade_prompt?: string;
  inquiries: PortfolioInquiry[];
}> => {
  return CommonApi('GET', '/inquiries/');
};

export const UpdateInquiryStatusApi = async (
  inquiryId: string,
  status: InquiryStatus,
  notes?: string
): Promise<PortfolioInquiry> => {
  return CommonApi('PATCH', `/inquiries/${inquiryId}/`, { status, notes });
};

export const DeleteInquiryApi = async (inquiryId: string): Promise<{ success: boolean }> => {
  return CommonApi('DELETE', `/inquiries/${inquiryId}/`);
};
```

---

## 4. TanStack React Query Hooks Collection

Save to `src/hooks/useAtelierQueries.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { GetStudioPlansApi, GetCurrentSubscriptionApi, CheckoutPlanApi } from '@/service/plans/PlanApi';
import { GetGalleriesApi, GetGalleryDetailApi, CreateGalleryApi, MoveMediaToSectionApi } from '@/service/galleries/GalleryApi';
import { GetInquiriesApi, UpdateInquiryStatusApi } from '@/service/inquiries/InquiryApi';
import { GetMyProfileApi, UpdateMyProfileApi } from '@/service/profile/ProfileApi';
import { GetEventsApi, MoveEventToGalleryApi } from '@/service/events/EventApi';

// 1. Studio Subscription & Quota
export const useCurrentSubscription = () => {
  return useQuery({
    queryKey: ['subscription', 'current'],
    queryFn: GetCurrentSubscriptionApi,
    staleTime: 1000 * 60 * 5, // 5 mins
  });
};

export const useStudioPlans = () => {
  return useQuery({
    queryKey: ['plans', 'all'],
    queryFn: GetStudioPlansApi,
    staleTime: 1000 * 60 * 60, // 1 hour
  });
};

// 2. Galleries Queries & Mutations
export const useGalleries = (filters?: { search?: string; status?: string }) => {
  return useQuery({
    queryKey: ['galleries', filters],
    queryFn: () => GetGalleriesApi(filters),
  });
};

export const useGalleryDetail = (idOrSlug: string) => {
  return useQuery({
    queryKey: ['gallery', idOrSlug],
    queryFn: () => GetGalleryDetailApi(idOrSlug),
    enabled: Boolean(idOrSlug),
  });
};

export const useCreateGallery = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: CreateGalleryApi,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['galleries'] });
      queryClient.invalidateQueries({ queryKey: ['subscription', 'current'] });
    },
  });
};

export const useMoveMediaSection = (galleryId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ mediaIds, targetSection }: { mediaIds: string[]; targetSection: string }) =>
      MoveMediaToSectionApi(galleryId, mediaIds, targetSection),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gallery', galleryId] });
    },
  });
};

// 3. Move Event to Gallery Mutation
export const useMoveEventToGallery = (eventId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: any) => MoveEventToGalleryApi(eventId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['events'] });
      queryClient.invalidateQueries({ queryKey: ['galleries'] });
      queryClient.invalidateQueries({ queryKey: ['subscription', 'current'] });
    },
  });
};

// 4. Inquiries
export const useInquiries = () => {
  return useQuery({
    queryKey: ['inquiries'],
    queryFn: GetInquiriesApi,
  });
};

export const useUpdateInquiryStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, notes }: { id: string; status: any; notes?: string }) =>
      UpdateInquiryStatusApi(id, status, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inquiries'] });
    },
  });
};
```

---

## 5. Plan Enforcement, Quota Guards & Upgrade Modals

When a photographer hits tier limits, the backend returns HTTP 403 with `upgrade_required: true`. Use this global interceptor / modal dispatcher:

```typescript
// src/components/billing/PlanUpgradeModal.tsx
import React from 'react';
import { useStudioPlans } from '@/hooks/useAtelierQueries';

interface PlanUpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  errorCode: string;
  errorMessage: string;
}

export const PlanUpgradeModal: React.FC<PlanUpgradeModalProps> = ({
  isOpen,
  onClose,
  errorCode,
  errorMessage,
}) => {
  const { data: plans } = useStudioPlans();
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
      <div className="relative w-full max-w-2xl rounded-2xl border border-white/10 bg-[#121214] p-8 text-white shadow-2xl">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-400">
          Studio Plan Limit Reached
        </div>
        <h2 className="text-2xl font-serif tracking-tight">Upgrade Your Studio Tier</h2>
        <p className="mt-2 text-sm text-neutral-400">{errorMessage}</p>

        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          {plans?.filter(p => p.id !== 'plan-standard-3m').map((plan) => (
            <div key={plan.id} className="rounded-xl border border-white/10 bg-neutral-900/60 p-5 hover:border-amber-500/50 transition">
              <span className="text-xs uppercase tracking-widest text-neutral-500">{plan.tag || plan.name}</span>
              <div className="mt-2 text-xl font-medium">₹{plan.total_price} <span className="text-xs text-neutral-400">/{plan.period_label}</span></div>
              <ul className="mt-4 space-y-2 text-xs text-neutral-300">
                {plan.features.slice(0, 4).map((f, i) => (
                  <li key={i} className="flex items-center gap-2">✓ {f}</li>
                ))}
              </ul>
              <a
                href="/dashboard/billing"
                className="mt-6 block text-center rounded-lg bg-white px-4 py-2 text-xs font-semibold text-black hover:bg-neutral-200 transition"
              >
                {plan.cta_text}
              </a>
            </div>
          ))}
        </div>

        <button
          onClick={onClose}
          className="absolute top-6 right-6 text-neutral-400 hover:text-white"
        >
          ✕
        </button>
      </div>
    </div>
  );
};
```

---

## 6. Component 1:1 Wiring Examples

### 6.1 Move Live Event to Gallery Drive (`MoveToGalleryModal.tsx`)
```typescript
import { useState } from 'react';
import { useMoveEventToGallery } from '@/hooks/useAtelierQueries';

export const MoveToGalleryModal = ({ event, isOpen, onClose }: any) => {
  const [targetMode, setTargetMode] = useState<'new' | 'existing'>('new');
  const [newTitle, setNewTitle] = useState(`${event.title} • Proofing Gallery`);
  const [assignments, setAssignments] = useState<Record<string, string>>({}); // mediaId -> Section

  const { mutate: moveEvent, isPending } = useMoveEventToGallery(event.id);

  const handleConfirm = () => {
    moveEvent(
      {
        target_mode: targetMode,
        new_gallery_title: targetMode === 'new' ? newTitle : undefined,
        category_assignments: assignments,
      },
      {
        onSuccess: (newGallery) => {
          onClose();
          window.location.href = `/dashboard/drive/${newGallery.id}`;
        },
      }
    );
  };

  if (!isOpen) return null;

  return (
    <div className="modal-container">
      <h3>Move Photos to Gallery Drive</h3>
      {/* Target Mode Toggle */}
      <div className="flex gap-4 my-4">
        <button onClick={() => setTargetMode('new')} className={targetMode === 'new' ? 'active' : ''}>
          Create New Gallery
        </button>
        <button onClick={() => setTargetMode('existing')} className={targetMode === 'existing' ? 'active' : ''}>
          Append to Existing
        </button>
      </div>

      {targetMode === 'new' && (
        <input
          type="text"
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="Gallery Title"
        />
      )}

      <button disabled={isPending} onClick={handleConfirm}>
        {isPending ? 'Transferring...' : 'Complete Transfer'}
      </button>
    </div>
  );
};
```

---

### 6.2 Move Photos to Another Section / Title (`GalleryDetailPage.tsx`)
```typescript
import { useState } from 'react';
import { useMoveMediaSection } from '@/hooks/useAtelierQueries';

export const ReassignSectionDropdown = ({ galleryId, selectedMediaIds, onComplete }: any) => {
  const [targetTitle, setTargetTitle] = useState('');
  const { mutate: moveMedia, isPending } = useMoveMediaSection(galleryId);

  const handleMove = (sectionTitle: string) => {
    moveMedia(
      {
        mediaIds: selectedMediaIds,
        targetSection: sectionTitle.trim().toUpperCase(),
      },
      {
        onSuccess: () => {
          onComplete();
        },
      }
    );
  };

  return (
    <div className="section-picker">
      <button onClick={() => handleMove('HALDI EDITED')}>Move to HALDI EDITED</button>
      <button onClick={() => handleMove('CEREMONY')}>Move to CEREMONY</button>
      <button onClick={() => handleMove('RECEPTION')}>Move to RECEPTION</button>
      <div className="new-section-row">
        <input
          value={targetTitle}
          onChange={(e) => setTargetTitle(e.target.value)}
          placeholder="NEW SECTION NAME"
        />
        <button disabled={!targetTitle || isPending} onClick={() => handleMove(targetTitle)}>
          Create & Move
        </button>
      </div>
    </div>
  );
};
```

---

### 6.3 Share Links, Expiration & QR Code (`ShareModal.tsx`)
```typescript
import { QRCodeSVG } from 'qrcode.react';

export const ShareModal = ({ gallery, isOpen, onClose }: any) => {
  const shareUrl = `${window.location.origin}/gallery/${gallery.slug || gallery.id}`;

  if (!isOpen) return null;

  return (
    <div className="share-modal">
      <h4>Client Delivery Share</h4>
      <input readOnly value={shareUrl} />
      <button onClick={() => navigator.clipboard.writeText(shareUrl)}>Copy Link</button>

      {/* Dynamic QR Code */}
      <div className="qr-box my-4">
        <QRCodeSVG value={shareUrl} size={180} level="H" includeMargin />
      </div>

      {/* Expiry display */}
      <div className="expiry-info text-xs text-neutral-400">
        {gallery.expires_at ? (
          <span>Valid until: {new Date(gallery.expires_at).toLocaleDateString()}</span>
        ) : (
          <span className="text-emerald-400">Permanent Unlimited Access (Studio Premium Elite)</span>
        )}
      </div>
    </div>
  );
};
```

---

### 6.4 AI Face Search (`AIFaceSearchBox.tsx`)
```typescript
import { useState } from 'react';
import { SearchGalleryByFaceApi } from '@/service/ai/FaceSearchApi';

export const AIFaceSearchBox = ({ galleryId, onResultsFound }: any) => {
  const [scanning, setScanning] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleSelfieUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setScanning(true);
    setErrorMsg('');

    try {
      const results = await SearchGalleryByFaceApi(galleryId, file);
      onResultsFound(results.matched_media_ids);
    } catch (err: any) {
      if (err.response?.data?.error_code === 'FACE_SEARCH_LOCKED') {
        setErrorMsg('AI Biometric Face Search is locked on this plan.');
      } else {
        setErrorMsg('No facial match found. Try a clearer selfie.');
      }
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="ai-search-box">
      <label className="cursor-pointer">
        {scanning ? 'Scanning Landmark Vectors...' : 'Find My Photos with Selfie'}
        <input type="file" accept="image/*" capture="user" onChange={handleSelfieUpload} className="hidden" />
      </label>
      {errorMsg && <p className="text-xs text-rose-400 mt-2">{errorMsg}</p>}
    </div>
  );
};
```

---

### 6.5 Inquiries Masking UI (`InquiriesPage.tsx`)
```typescript
import { useInquiries } from '@/hooks/useAtelierQueries';

export const InquiriesPage = () => {
  const { data, isLoading } = useInquiries();

  if (isLoading) return <div>Loading Inquiries...</div>;

  return (
    <div className="inquiries-container">
      {!data?.has_full_inquiry_access && (
        <div className="banner bg-amber-500/10 border border-amber-500/30 p-4 rounded-xl mb-6">
          <p className="text-amber-400 font-medium">Standard Quarterly Mask Active</p>
          <p className="text-xs text-neutral-400 mt-1">{data?.upgrade_prompt}</p>
        </div>
      )}

      <div className="space-y-4">
        {data?.inquiries.map((inq) => (
          <div key={inq.id} className={`inquiry-card ${inq.is_locked ? 'opacity-50 blur-[0.5px]' : ''}`}>
            <h5>{inq.clientName}</h5>
            <p>Email: {inq.clientEmail}</p>
            <p>Phone: {inq.clientPhone}</p>
            <p>Budget: {inq.budget}</p>
            {inq.is_locked && (
              <span className="badge text-xs bg-red-500/20 text-red-400 px-2 py-0.5 rounded">
                Contact Details Locked
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
```

---

### 6.6 Watermark & Settings Suite (`SettingsPage.tsx`)
```typescript
import { useState } from 'react';
import { UpdateWatermarkApi } from '@/service/profile/ProfileApi';

export const WatermarkSettings = ({ profile }: any) => {
  const [enabled, setEnabled] = useState(profile.enable_watermark);
  const [text, setText] = useState(profile.watermark_text || '© EX SHARE');
  const [opacity, setOpacity] = useState(profile.watermark_opacity || 0.45);
  const [position, setPosition] = useState(profile.watermark_position || 'bottom-right');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await UpdateWatermarkApi({
        enable_watermark: enabled,
        watermark_text: text,
        watermark_opacity: opacity,
        watermark_position: position,
      });
      alert('Watermark settings saved!');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="watermark-card space-y-4">
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enable Studio Watermark on Client Deliveries
      </label>

      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Watermark Text" />

      <div>
        <label>Opacity: {Math.round(opacity * 100)}%</label>
        <input
          type="range"
          min="0.1"
          max="1.0"
          step="0.05"
          value={opacity}
          onChange={(e) => setOpacity(parseFloat(e.target.value))}
        />
      </div>

      <select value={position} onChange={(e) => setPosition(e.target.value as any)}>
        <option value="bottom-right">Bottom Right</option>
        <option value="bottom-left">Bottom Left</option>
        <option value="top-right">Top Right</option>
        <option value="center">Center</option>
        <option value="tiled">Tiled Across Photo</option>
      </select>

      <button disabled={saving} onClick={handleSave}>
        {saving ? 'Saving...' : 'Save Watermark Preferences'}
      </button>
    </div>
  );
};
```

---

## 7. Verification Checklist

| Step | Action | Status |
| :--- | :--- | :--- |
| 1 | Run `python manage.py makemigrations` and `python manage.py migrate` | ✅ Completed |
| 2 | Seed plans: `python manage.py seed_studio_plans` | ✅ Completed |
| 3 | Check Django system status: `python manage.py check` | ✅ OK (0 issues) |
| 4 | Ensure `.env` in React app points to `VITE_API_BASE_URL=http://localhost:8000/api` | Ready |
| 5 | Verify Axios instance has `withCredentials: true` for HTTP-only JWT cookies | Ready |
