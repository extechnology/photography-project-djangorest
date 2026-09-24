# Frontend Connection Documentation: Studio Plans & Photo Uploads

This document provides complete instructions, TypeScript definitions, and API client examples for integrating the frontend (React / Vite / Next.js) with the Django REST backend.

---

## 1. General Configuration & Authentication

### Base URL
```typescript
const BASE_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';
```

### Authentication Options (Cookies & Bearer Header)
The backend supports **both** HTTP-only cookie-based authentication and Authorization header authentication:

1. **HTTP-only Cookies (Recommended for Web)**:
   If your frontend relies on cookies set by the login or refresh endpoints (`access_token` and `refresh_token`), simply enable credentials in your HTTP client:
   ```typescript
   // Axios configuration
   axios.defaults.withCredentials = true;

   // Or with fetch
   fetch(url, {
     credentials: 'include'
   });
   ```
   *No manual `Authorization` header is required when `access_token` cookie is present.*

2. **Authorization Header (Fallback / Mobile Apps)**:
   ```typescript
   headers: {
     'Authorization': `Bearer ${accessToken}`,
     'Content-Type': 'application/json'
   }
   ```


---

## 2. Studio Plans & Subscription Endpoints

> **Note**: For routing flexibility, all endpoints are accessible via both `/api/plans/` and `/api/subscriptions/`.

### Summary Table

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/plans/` | Retrieve public list of active studio plans | No |
| `GET` | `/api/plans/current/` | Get current active subscription, days left & storage stats | **Yes** |
| `POST` | `/api/plans/checkout/` | Initiate plan checkout (`direct` or `razorpay`) | **Yes** |
| `POST` | `/api/plans/verify/` | Verify Razorpay payment signature & activate quota | **Yes** |
| `POST` | `/api/plans/cancel/` | Turn off auto-renewal for current subscription | **Yes** |

---

### A. List Studio Plans: `GET /api/plans/`
Retrieves all public studio tiers matching the UI cards (`Standard Quarterly`, `Standard Annual`, `Studio Premium Elite`).

#### Request:
```http
GET /api/plans/ HTTP/1.1
Host: 127.0.0.1:8000
```

#### Success Response (`200 OK`):
```json
[
  {
    "id": "plan-standard-3m",
    "name": "Standard Quarterly",
    "subtitle": "For 03 Months • Ideal For Getting Started",
    "tier": "standard",
    "billing_cycle": "quarterly",
    "period_label": "For 03 Months",
    "duration_months": 3,
    "monthly_price": "800.00",
    "original_monthly_price": "1100.00",
    "total_price": "2400.00",
    "billing_text": "₹800 / Month • Billed Quarterly (₹2,400)",
    "currency": "INR",
    "tag": "",
    "tag_type": "default",
    "image_storage": "200 GB",
    "video_storage": "10 GB",
    "storage_limit_bytes": 225485783040,
    "max_galleries": 15,
    "gallery_expiry_days": 90,
    "face_search_enabled": false,
    "max_events": 5,
    "allowed_templates": ["editorial", "masonry"],
    "allowed_portfolio_templates": ["editorial", "masonry"],
    "max_portfolio_posts": 10,
    "max_inquiries": 10,
    "has_full_inquiry_access": false,
    "inquiry_access": "Random 10 Inquiries",
    "can_upgrade_storage": false,
    "max_upgrade_image_gb": 200,
    "features": [
      "200 GB High-Speed Image Storage",
      "10 GB 4K Video Delivery",
      "For 03 Months Hosting",
      "Up to 15 Active Client Galleries",
      "90 Days Gallery Access Validity",
      "5 Event Section Albums (30-Day Window)",
      "Editorial & Masonry Gallery Templates",
      "Photographer Portfolio (10 Showcase Posts)",
      "Random 10 Client Inquiries Access (Upgrade to view all)",
      "PIN Security & Custom Watermark Suite",
      "Priority Delivery Speeds"
    ],
    "cta_text": "Choose Standard (3 Months)",
    "is_active": true,
    "sort_order": 1
  },
  {
    "id": "plan-standard-1y",
    "name": "Standard Annual",
    "subtitle": "For 01 Year • Best Value For Photographers",
    "tier": "standard",
    "billing_cycle": "annual",
    "period_label": "For 01 Year",
    "duration_months": 12,
    "monthly_price": "800.00",
    "original_monthly_price": "1100.00",
    "total_price": "9600.00",
    "billing_text": "₹800 / Month • Billed Annually (₹9,600)",
    "currency": "INR",
    "tag": "MOST POPULAR",
    "tag_type": "popular",
    "image_storage": "200 GB",
    "video_storage": "10 GB",
    "storage_limit_bytes": 225485783040,
    "max_galleries": 50,
    "gallery_expiry_days": 365,
    "face_search_enabled": true,
    "max_events": 25,
    "allowed_templates": ["editorial", "masonry"],
    "allowed_portfolio_templates": ["editorial", "masonry"],
    "max_portfolio_posts": 30,
    "max_inquiries": 0,
    "has_full_inquiry_access": true,
    "inquiry_access": "All Inquiries",
    "can_upgrade_storage": false,
    "max_upgrade_image_gb": 200,
    "features": [
      "200 GB High-Speed Image Storage",
      "10 GB 4K Video Delivery",
      "For 01 Year Uninterrupted Hosting",
      "Up to 50 Active Client Galleries",
      "365 Days Gallery Access Validity",
      "AI Biometric Face Search Enabled",
      "25 Event Section Albums (90-Day Window)",
      "Editorial & Masonry Gallery Templates",
      "Photographer Portfolio (30 Showcase Posts)",
      "Full Access to All Client Inquiries",
      "PIN Security & Custom Watermark Suite",
      "Priority Delivery Speeds"
    ],
    "cta_text": "Choose Standard (1 Year)",
    "is_active": true,
    "sort_order": 2
  },
  {
    "id": "plan-premium-elite",
    "name": "Studio Premium Elite",
    "subtitle": "2xStandard Plan • Maximum Storage & Dedicated Video Bandwidth",
    "tier": "premium",
    "billing_cycle": "annual",
    "period_label": "For 01 Year",
    "duration_months": 12,
    "monthly_price": "1800.00",
    "original_monthly_price": "2200.00",
    "total_price": "21600.00",
    "billing_text": "₹1,800 / Month • Billed Annually (₹21,600)",
    "currency": "INR",
    "tag": "2xStandard Plan",
    "tag_type": "popular",
    "image_storage": "600 GB",
    "video_storage": "50 GB",
    "storage_limit_bytes": 697932185600,
    "max_galleries": 0,
    "gallery_expiry_days": 0,
    "face_search_enabled": true,
    "max_events": 0,
    "allowed_templates": ["editorial", "masonry", "cinematic", "minimal"],
    "allowed_portfolio_templates": ["editorial", "masonry", "cinematic", "minimal"],
    "max_portfolio_posts": 0,
    "max_inquiries": 0,
    "has_full_inquiry_access": true,
    "inquiry_access": "All Inquiries",
    "can_upgrade_storage": true,
    "max_upgrade_image_gb": 1000,
    "features": [
      "600 GB Image Storage (Upgradeable to 1000 GB)",
      "50 GB 4K Video Delivery",
      "2x Standard Plan Performance & Quota",
      "Unlimited Client Galleries (No Cap)",
      "Unlimited Gallery Expiry (Permanent)",
      "Dedicated High-Bandwidth Cloud Delivery",
      "VIP AI Face Search & Discovery",
      "Unlimited Event Section Albums",
      "All 4 Layout Templates (Editorial, Masonry, Cinematic, Minimal)",
      "Photographer Portfolio (Unlimited Posts & Custom Domain)",
      "Full & Unlimited Access to All Client Inquiries",
      "Custom Studio Watermarking Suite & White-Labeling",
      "VIP Support & Early Access to New Templates"
    ],
    "cta_text": "Choose Studio Premium Elite",
    "is_active": true,
    "sort_order": 3
  }
]
```

---

### B. Current Subscription & Usage: `GET /api/plans/current/`
Retrieves the logged-in photographer's subscription status, renewal date, and real-time storage metrics.

#### Request:
```http
GET /api/plans/current/ HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <jwt_access_token>
```

#### Success Response (`200 OK`):
```json
{
  "id": "d3b07384-d113-468b-965a-04664912fa8e",
  "status": "active",
  "plan": {
    "id": "plan-standard-1y",
    "name": "Standard Annual",
    "tier": "standard",
    "billing_cycle": "annual",
    "duration_months": 12,
    "total_price": "9600.00",
    "currency": "INR"
  },
  "start_date": "2026-09-17T10:00:00Z",
  "expiry_date": "2027-09-17T10:00:00Z",
  "days_remaining": 365,
  "storage": {
    "used_bytes": 30814981120,
    "limit_bytes": 225485783040,
    "used_gb": 28.7,
    "limit_gb": 210.0,
    "used_percentage": 13.7
  },
  "auto_renew": true,
  "payment_gateway_ref": "pay_987654321"
}
```

---

### C. Initiate Checkout: `POST /api/plans/checkout/`
Supports two gateway modes:
1. **`gateway="direct"`**: Immediately activates the plan without calling Razorpay (ideal for development, demo, or testing environments).
2. **`gateway="razorpay"`**: Generates Razorpay order credentials in INR paise for checkout dialog.

#### 1. Direct Mode Request (Dev/Testing):
```http
POST /api/plans/checkout/ HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <jwt_access_token>
Content-Type: application/json

{
  "plan_id": "plan-standard-1y",
  "gateway": "direct"
}
```

#### Direct Mode Response (`200 OK`):
```json
{
  "status": "success",
  "message": "Successfully activated Standard Annual directly.",
  "direct_activated": true,
  "subscription": {
    "id": "d3b07384-d113-468b-965a-04664912fa8e",
    "status": "active",
    "plan": {
      "id": "plan-standard-1y",
      "name": "Standard Annual",
      "tier": "standard",
      "billing_cycle": "annual"
    },
    "days_remaining": 365,
    "storage": {
      "used_bytes": 0,
      "limit_bytes": 225485783040,
      "used_gb": 0.0,
      "limit_gb": 210.0,
      "used_percentage": 0.0
    },
    "auto_renew": true
  }
}
```

#### 2. Razorpay Mode Request:
```http
POST /api/plans/checkout/ HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <jwt_access_token>
Content-Type: application/json

{
  "plan_id": "plan-standard-1y",
  "gateway": "razorpay"
}
```

#### Razorpay Mode Response (`200 OK`):
```json
{
  "status": "success",
  "direct_activated": false,
  "order_id": "order_7a3d8f1e2c9b4a5d",
  "amount": 9600.0,
  "amount_paise": 960000,
  "currency": "INR",
  "key_id": "rzp_test_placeholder",
  "plan_id": "plan-standard-1y",
  "payment_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### D. Verify Payment: `POST /api/plans/verify/`
Called after the Razorpay checkout callback returns `razorpay_payment_id` and `razorpay_signature`.

#### Request:
```http
POST /api/plans/verify/ HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <jwt_access_token>
Content-Type: application/json

{
  "plan_id": "plan-standard-1y",
  "gateway_order_id": "order_7a3d8f1e2c9b4a5d",
  "gateway_payment_id": "pay_O4LkJ98d34Zz8a",
  "gateway_signature": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```
*(Note: Parameters named `razorpay_order_id`, `razorpay_payment_id`, and `razorpay_signature` are also automatically recognized).*

#### Success Response (`200 OK`):
```json
{
  "status": "success",
  "message": "Payment verified. Standard Annual subscription is now active.",
  "subscription": {
    "id": "d3b07384-d113-468b-965a-04664912fa8e",
    "status": "active",
    "plan": {
      "id": "plan-standard-1y",
      "name": "Standard Annual",
      "tier": "standard"
    },
    "days_remaining": 365,
    "storage": {
      "used_bytes": 0,
      "limit_bytes": 225485783040,
      "limit_gb": 210.0,
      "used_percentage": 0.0
    },
    "auto_renew": true
  }
}
```

#### Error Response (`400 Bad Request`):
```json
{
  "detail": "Payment verification failed: invalid signature."
}
```

---

### E. Cancel Auto-Renewal: `POST /api/plans/cancel/`
Turns off auto-renewal for the subscription while maintaining active access until the current `expiry_date`.

#### Request:
```http
POST /api/plans/cancel/ HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <jwt_access_token>
Content-Type: application/json

{}
```

#### Success Response (`200 OK`):
```json
{
  "status": "success",
  "message": "Auto-renewal has been turned off for your studio subscription.",
  "auto_renew": false
}
```

---

## 3. Photo Uploads with Nude Detection

Uploaded photos are scanned on the backend using NudeNet. If an image contains explicit nudity (e.g. exposed breasts, genitalia, buttocks, anus), it is rejected with an HTTP `400 Bad Request`.

### Uploading to a Post: `POST /api/photographers/posts/<post_id>/images/upload/`

#### Request (Multipart Form Data):
```http
POST /api/photographers/posts/42/images/upload/ HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <jwt_access_token>
Content-Type: multipart/form-data; boundary=----WebKitFormBoundaryXYZ

------WebKitFormBoundaryXYZ
Content-Disposition: form-data; name="images"; filename="wedding1.jpg"
Content-Type: image/jpeg

<binary data>
------WebKitFormBoundaryXYZ--
```

#### Success Response (`201 Created`):
```json
{
  "message": "Images uploaded successfully",
  "data": [
    {
      "id": 105,
      "post": 42,
      "image": "/media/post_images/wedding1.jpg",
      "created_at": "2026-09-17T12:30:00Z"
    }
  ]
}
```

#### Rejection Response when Nudity is Detected (`400 Bad Request`):
```json
{
  "message": "Upload rejected: Inappropriate or explicit content detected in one or more photos.",
  "rejected_files": [
    {
      "filename": "forbidden_photo.jpg",
      "reason": "Explicit or nude content detected (Female Breast Exposed)"
    }
  ]
}
```

---

## 4. Frontend TypeScript Integration (Copy-Paste Ready)

### TypeScript Interfaces (`src/types/plan.types.ts`)
```typescript
export interface StudioPlan {
  id: string;
  name: string;
  subtitle: string;
  tier: 'standard' | 'premium' | 'custom';
  billing_cycle: 'quarterly' | 'annual' | 'monthly';
  period_label: string;
  duration_months: number;
  monthly_price: string;
  original_monthly_price: string | null;
  total_price: string;
  billing_text: string;
  currency: string;
  tag: string;
  tag_type: 'default' | 'popular' | 'current';
  image_storage: string;
  video_storage: string;
  storage_limit_bytes: number;
  max_galleries: number; // 0 = unlimited
  gallery_expiry_days: number; // 0 = unlimited
  face_search_enabled: boolean;
  max_events: number; // 0 = unlimited
  allowed_templates: string[];
  allowed_portfolio_templates: string[];
  max_portfolio_posts: number; // 0 = unlimited
  max_inquiries: number; // 0 = unlimited / all inquiries
  has_full_inquiry_access: boolean;
  inquiry_access: string; // e.g. "Random 10 Inquiries" or "All Inquiries"
  can_upgrade_storage: boolean;
  max_upgrade_image_gb: number;
  features: string[];
  cta_text: string;
  is_active: boolean;
  sort_order: number;
}

export interface StorageQuotaMetrics {
  used_bytes: number;
  limit_bytes: number;
  used_gb: number;
  limit_gb: number;
  used_percentage: number;
}

export interface CurrentSubscription {
  id: string;
  status: 'active' | 'expired' | 'pending' | 'cancelled';
  plan: {
    id: string;
    name: string;
    tier: string;
    billing_cycle: string;
    duration_months?: number;
    total_price?: string;
    currency?: string;
  };
  start_date: string;
  expiry_date: string;
  days_remaining: number;
  storage: StorageQuotaMetrics;
  auto_renew: boolean;
  payment_gateway_ref?: string;
}

export interface CheckoutOrderResponse {
  status: string;
  direct_activated: boolean;
  order_id?: string;
  amount?: number;
  amount_paise?: number;
  currency?: string;
  key_id?: string;
  plan_id?: string;
  payment_id?: string;
  subscription?: CurrentSubscription;
}

export interface VerifyPaymentPayload {
  plan_id: string;
  gateway_order_id: string;
  gateway_payment_id: string;
  gateway_signature: string;
}
```

---

### Axios Service (`src/services/planApi.ts`)
```typescript
import axios from 'axios';
import {
  StudioPlan,
  CurrentSubscription,
  CheckoutOrderResponse,
  VerifyPaymentPayload
} from '../types/plan.types';

const apiClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000',
});

// Attach JWT token automatically
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const PlanApi = {
  /**
   * Fetches all active studio plans catalog
   */
  async getStudioPlans(): Promise<StudioPlan[]> {
    const response = await apiClient.get<StudioPlan[]>('/api/plans/');
    return response.data;
  },

  /**
   * Fetches the photographer's current subscription & storage meters
   */
  async getCurrentSubscription(): Promise<CurrentSubscription> {
    const response = await apiClient.get<CurrentSubscription>('/api/plans/current/');
    return response.data;
  },

  /**
   * Initiates checkout for a plan.
   * @param planId Plan ID e.g. 'plan-standard-1y'
   * @param gateway 'direct' for instant dev/demo activation or 'razorpay' for live payment
   */
  async checkoutPlan(planId: string, gateway: 'direct' | 'razorpay' = 'direct'): Promise<CheckoutOrderResponse> {
    const response = await apiClient.post<CheckoutOrderResponse>('/api/plans/checkout/', {
      plan_id: planId,
      gateway,
    });
    return response.data;
  },

  /**
   * Verifies Razorpay payment signature and activates the quota
   */
  async verifyPayment(payload: VerifyPaymentPayload): Promise<{ status: string; subscription: CurrentSubscription }> {
    const response = await apiClient.post('/api/plans/verify/', payload);
    return response.data;
  },

  /**
   * Cancels auto-renewal
   */
  async cancelAutoRenew(): Promise<{ status: string; auto_renew: boolean }> {
    const response = await apiClient.post('/api/plans/cancel/');
    return response.data;
  },
};
```

---

### Razorpay Integration Hook / Component Example
```typescript
import React, { useState } from 'react';
import { PlanApi } from '../services/planApi';
import { StudioPlan } from '../types/plan.types';

declare global {
  interface Window {
    Razorpay: any;
  }
}

export const usePlanUpgrade = (onSuccess: () => void) => {
  const [loading, setLoading] = useState(false);

  const upgradePlan = async (plan: StudioPlan, useDirect = false) => {
    setLoading(true);
    try {
      if (useDirect) {
        // Direct Activation (Dev / Testing / Demo)
        await PlanApi.checkoutPlan(plan.id, 'direct');
        alert(`Successfully activated ${plan.name}!`);
        onSuccess();
        return;
      }

      // Razorpay Checkout
      const order = await PlanApi.checkoutPlan(plan.id, 'razorpay');

      const options = {
        key: order.key_id,
        amount: order.amount_paise,
        currency: order.currency,
        name: 'Photography Studio Cloud',
        description: `Upgrade to ${plan.name}`,
        order_id: order.order_id,
        handler: async function (response: any) {
          try {
            await PlanApi.verifyPayment({
              plan_id: plan.id,
              gateway_order_id: response.razorpay_order_id,
              gateway_payment_id: response.razorpay_payment_id,
              gateway_signature: response.razorpay_signature,
            });
            alert(`Payment successful! Your new storage limit of ${plan.image_storage} is active.`);
            onSuccess();
          } catch (err: any) {
            alert(err.response?.data?.detail || 'Payment verification failed.');
          }
        },
        theme: {
          color: '#4F46E5',
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Checkout failed.');
    } finally {
      setLoading(false);
    }
  };

  return { upgradePlan, loading };
};
```

---

## 6. Client Inquiries & Leads API

### Summary Table

| Method | Endpoint | Description | Auth Required | Plan Tier Rule |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/photographers/inquiries/` | Public inquiry submission by client/guest | No | Open to all clients |
| `GET` | `/api/photographers/inquiries/` | List inquiries for logged-in photographer | **Yes** | **Standard 3M**: Random 10 inquiries (`random_sample`)<br>**Standard 1Y & Premium**: All inquiries (`full_access`) |
| `GET` | `/api/photographers/inquiries/<uuid:id>/` | Retrieve inquiry detail | **Yes** | Active plan |
| `PATCH` | `/api/photographers/inquiries/<uuid:id>/` | Update inquiry status (`contacted`, `booked`, etc.) | **Yes** | Photographer |
| `DELETE` | `/api/photographers/inquiries/<uuid:id>/` | Delete inquiry | **Yes** | Photographer |

#### List Inquiries Response (`GET /api/photographers/inquiries/`):
```json
{
  "access_tier": "random_sample",
  "inquiry_limit": 10,
  "total_available": 42,
  "count": 10,
  "inquiries": [
    {
      "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "photographer": 1,
      "photographer_name": "Apex Studio",
      "studio_name": "Apex Wedding & Studio",
      "client_name": "Sarah Connor",
      "client_email": "sarah@example.com",
      "client_phone": "+919876543210",
      "event_type": "Wedding",
      "event_date": "2026-12-15",
      "location": "Mumbai",
      "budget": "₹1,50,000",
      "message": "Looking for wedding photography deliverables.",
      "status": "new",
      "created_at": "2026-09-22T10:00:00Z",
      "updated_at": "2026-09-22T10:00:00Z"
    }
  ]
}
```
