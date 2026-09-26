# Gallery & Media Upload API Documentation (Frontend Reference)

> **Document Version:** 2.1.0  
> **Target Frontend Stack:** React 19 + TypeScript + Vite + TanStack Query v5 + Axios (`axiosInstance.ts`)  
> **Backend Base URL:** `http://localhost:8000/api` (with `withCredentials: true`)  
> **Status:** Production Ready (Duplicate URLs Removed & Canonical Endpoints Defined)

---

## 1. Summary of Canonical URL Routes & URL Deduplication

To eliminate confusion between redundant endpoints, the routing has been cleaned and standardized:

| Previous Redundant Route | Canonical Route | HTTP Method | Purpose |
| :--- | :--- | :--- | :--- |
| `POST /api/galleries/{id}/media/upload/` *(Removed)* | `POST /api/galleries/{gallery_id}/upload/` | `POST` | **Standard & High-Capacity Multipart Batch Upload** |
| `/api/storage/galleries/...` *(Alias)* | `/api/galleries/...` | Any | **Canonical Root Endpoint** (Both work, `/api/galleries/` is standard) |

---

## 2. TypeScript Data Contracts (`src/types/gallery.ts`)

```typescript
export type GalleryStatus = 'active' | 'delivered' | 'draft' | 'archived';
export type GalleryTemplateId = 'editorial' | 'masonry' | 'cinematic' | 'minimal';
export type MediaType = 'photo' | 'video';

export interface MediaItem {
  id: string; // UUID
  gallery: string; // Gallery UUID
  media_type: MediaType;
  title: string;
  section_title: string; // e.g. "CEREMONY", "RECEPTION", "Highlights"
  caption: string;
  original_filename: string;
  file_size: number; // in bytes
  width?: number | null;
  height?: number | null;
  aspect_ratio?: number | null;
  duration?: string | null; // For videos (e.g. "02:30")
  display_order: number;
  is_cover: boolean;
  is_favorite: boolean;
  mime_type: string;
  file_extension: string;
  processing_status: 'pending' | 'processing' | 'ready' | 'failed';
  upload_status: 'reserved' | 'uploading' | 'completed' | 'failed';
  downloads_count: number;
  thumbnail_url: string; // WebP derivative
  preview_url: string;   // High-res preview WebP
  file_url: string;      // High-res viewable asset URL
  download_url: string;  // Original high-res secure download: /api/galleries/media/{id}/download/
  created_at: string;
}

export interface Gallery {
  id: string; // UUID
  slug: string;
  title: string;
  client_name: string;
  client_email?: string;
  event_date: string; // YYYY-MM-DD
  status: GalleryStatus;
  template_id: GalleryTemplateId;
  sections: string[]; // e.g. ["Highlights", "CEREMONY", "RECEPTION"]
  cover_image?: string;
  cover_image_url?: string;
  is_password_protected: boolean;
  allow_downloads: boolean;
  allow_favorites: boolean;
  face_search_enabled: boolean;
  views_count: number;
  photos_count: number;
  videos_count: number;
  share_url?: string;
  media?: MediaItem[];
  created_at: string;
  updated_at: string;
}

export interface GalleryFilterParams {
  search?: string; // Search title or client_name
  status?: 'active' | 'delivered';
  date_filter?: 'this-year' | 'last-year' | 'last-30-days' | 'last-3-months' | 'last-6-months' | 'custom' | string;
  date_from?: string; // YYYY-MM-DD
  date_to?: string;   // YYYY-MM-DD
  sort?: 'date-desc' | 'date-asc' | 'name' | 'photos';
}

export interface StorageUsageMetrics {
  used_bytes: number;
  limit_bytes: number;
  used_gb: number;
  limit_gb: number;
  used_percentage: number;
}

export interface StorageLimitExceededError {
  upgrade_required: true;
  code: 'STORAGE_LIMIT_EXCEEDED';
  error_code: 'STORAGE_LIMIT_EXCEEDED';
  message: string;
  available_bytes: number;
  requested_bytes: number;
}

export interface BatchUploadResponse {
  message: string;
  total_uploaded: number;
  media: MediaItem[];
  storage_usage: StorageUsageMetrics;
}

export interface MoveMediaSectionRequest {
  media_ids: string[];
  target_section: string;
}

export interface MoveMediaSectionResponse {
  status: 'success';
  message: string;
  updated_count: number;
  section: string;
  sections: string[];
}
```

---

## 3. Gallery Management Endpoints

### 3.1 List Galleries (`GET /api/galleries/`)
Supports 100% server-side searching, status filtering, date presets, and sorting.

- **Query Parameters:**
  - `search` *(string)*: Case-insensitive search on `title` or `client_name`.
  - `status` *(string)*: `'active'` or `'delivered'`.
  - `date_filter` *(string)*: `'this-year'`, `'last-year'`, `'last-30-days'`, `'last-3-months'`, `'last-6-months'`, `'year-YYYY'`, `'custom'`.
  - `date_from` / `date_to` *(string)*: `YYYY-MM-DD` (used with `date_filter=custom` or directly).
  - `sort` *(string)*: `'date-desc'` (default), `'date-asc'`, `'name'`, `'photos'`.

**Response (`HTTP 200 OK`):**
```json
[
  {
    "id": "29a3f20d-17e1-4c98-a917-d58bd87a1efc",
    "slug": "roy-wedding-2026",
    "title": "Roy Wedding Celebration",
    "client_name": "Rahul & Priya Roy",
    "event_date": "2026-10-15",
    "status": "active",
    "template_id": "editorial",
    "cover_image": "https://cdn.yourdomain.com/previews/cover.webp",
    "photos_count": 184,
    "views_count": 28,
    "allow_downloads": true,
    "allow_favorites": true,
    "face_search_enabled": true
  }
]
```

---

### 3.2 Create Gallery (`POST /api/galleries/`)
Creates a new gallery. Enforces active subscription plan limits (`max_galleries`) and layout template access.

**Payload (`application/json`):**
```json
{
  "title": "Summer Beach Wedding",
  "client_name": "Sarah & Dave",
  "client_email": "sarah@example.com",
  "event_date": "2026-11-20",
  "template_id": "editorial",
  "allow_downloads": true,
  "allow_favorites": true
}
```

**Quota Enforcement Response (`HTTP 403 Forbidden`):**
```json
{
  "upgrade_required": true,
  "code": "GALLERY_LIMIT_EXCEEDED",
  "error_code": "GALLERY_LIMIT_EXCEEDED",
  "message": "Gallery quota reached for your Standard Quarterly (15/15). Upgrade to unlock more client galleries.",
  "detail": "Your plan allows up to 15 active galleries. Please upgrade to unlock more."
}
```

---

### 3.3 Get Gallery Detail (`GET /api/galleries/{id_or_slug}/`)
Returns full gallery metadata, settings, and the list of non-deleted `media` items. Accepts both UUID or custom slug.

**Response (`HTTP 200 OK`):**
```json
{
  "id": "29a3f20d-17e1-4c98-a917-d58bd87a1efc",
  "slug": "roy-wedding-2026",
  "title": "Roy Wedding Celebration",
  "client_name": "Rahul & Priya Roy",
  "status": "active",
  "template_id": "editorial",
  "photos_count": 2,
  "media": [
    {
      "id": "78c946bc-2651-40be-bd6f-99f579ec7fcf",
      "original_filename": "ceremony_01.jpg",
      "file_size": 4589200,
      "thumbnail_url": "http://localhost:8000/media/storage_objects/galleries/thumbnails/78c946bc.webp",
      "preview_url": "http://localhost:8000/media/storage_objects/galleries/previews/78c946bc.webp",
      "download_url": "http://localhost:8000/api/galleries/media/78c946bc-2651-40be-bd6f-99f579ec7fcf/download/",
      "is_cover": true,
      "is_favorite": false
    }
  ]
}
```

> **Note on Absolute Media Paths:**
> All media endpoints and serializers receive `context={'request': request}`. In development (e.g. Vite running on port `5173` and Django on port `8000`), all media URLs (`thumbnail_url`, `preview_url`, `file_url`, `download_url`, and `cover_image`) are automatically formatted as fully-qualified absolute URLs (e.g., `http://localhost:8000/...`), preventing frontend 404s.


---

### 3.4 Status Switching & Partial Update (`PATCH /api/galleries/{id_or_slug}/`)
Used by the frontend to toggle gallery status between active proofing and final delivered state:

**Payload (`application/json`):**
```json
{
  "status": "delivered"
}
```
**Response (`HTTP 200 OK`):**
```json
{
  "id": "29a3f20d-17e1-4c98-a917-d58bd87a1efc",
  "status": "delivered",
  "title": "Roy Wedding Celebration"
}
```

---

## 4. Media Upload Endpoints (All Files)

### 4.1 Standard & High-Capacity Batch Upload (`POST /api/galleries/{gallery_id}/upload/`)
The primary and canonical upload endpoint. Designed for both single photo uploads and high-capacity batch uploads up to **2,000+ files / 10 GB per request**.

- **Content-Type:** `multipart/form-data`
- **Accepted File Field Names:** `photos`, `images`, or `files` (supports multiple items appended with the same key).
- **Optional Form Fields:**
  - `section_title` *(string)*: Label/section to organize photos into.
  - `type` *(string)*: `'photo'` (default) or `'video'`.

#### Example Multipart Request:
```http
POST /api/galleries/29a3f20d-17e1-4c98-a917-d58bd87a1efc/upload/ HTTP/1.1
Content-Type: multipart/form-data; boundary=----WebKitFormBoundaryXYZ

------WebKitFormBoundaryXYZ
Content-Disposition: form-data; name="photos"; filename="wedding_001.jpg"
Content-Type: image/jpeg

<binary content>
------WebKitFormBoundaryXYZ
Content-Disposition: form-data; name="photos"; filename="wedding_002.jpg"
Content-Type: image/jpeg

<binary content>
------WebKitFormBoundaryXYZ
Content-Disposition: form-data; name="section_title"

Ceremony
------WebKitFormBoundaryXYZ--
```

**Success Response (`HTTP 201 Created`):**
```json
{
  "message": "Successfully uploaded 2 files.",
  "total_uploaded": 2,
  "media": [
    {
      "id": "c1f7b9de-2c6e-4735-86aa-cf615174092b",
      "gallery": "29a3f20d-17e1-4c98-a917-d58bd87a1efc",
      "media_type": "photo",
      "title": "wedding_001",
      "section_title": "CEREMONY",
      "original_filename": "wedding_001.jpg",
      "file_size": 3840210,
      "width": 3840,
      "height": 2160,
      "aspect_ratio": 1.77,
      "duration": null,
      "thumbnail_url": "https://cdn.example.com/thumbnails/c1f7b9de.webp",
      "preview_url": "https://cdn.example.com/previews/c1f7b9de.webp",
      "file_url": "https://cdn.example.com/previews/c1f7b9de.webp",
      "download_url": "/api/galleries/media/c1f7b9de-2c6e-4735-86aa-cf615174092b/download/",
      "is_cover": false,
      "is_favorite": false,
      "display_order": 0,
      "created_at": "2026-09-25T14:30:00Z"
    },
    {
      "id": "d2f8a8ce-1b5d-4824-95bb-de726285183c",
      "gallery": "29a3f20d-17e1-4c98-a917-d58bd87a1efc",
      "media_type": "photo",
      "title": "wedding_002",
      "section_title": "CEREMONY",
      "original_filename": "wedding_002.jpg",
      "file_size": 4120300,
      "width": 3840,
      "height": 2160,
      "aspect_ratio": 1.77,
      "duration": null,
      "thumbnail_url": "https://cdn.example.com/thumbnails/d2f8a8ce.webp",
      "preview_url": "https://cdn.example.com/previews/d2f8a8ce.webp",
      "file_url": "https://cdn.example.com/previews/d2f8a8ce.webp",
      "download_url": "/api/galleries/media/d2f8a8ce-1b5d-4824-95bb-de726285183c/download/",
      "is_cover": false,
      "is_favorite": false,
      "display_order": 0,
      "created_at": "2026-09-25T14:30:01Z"
    }
  ],
  "storage_usage": {
    "used_bytes": 15420300,
    "limit_bytes": 697932185600,
    "used_gb": 0.01,
    "limit_gb": 650.0,
    "used_percentage": 0.0
  }
}
```

#### Upload Error Responses:
- **Storage Limit Exceeded (`HTTP 403 Forbidden`):**
  Triggered when the photographer's active subscription storage quota would be exceeded by the upload.
  ```json
  {
    "upgrade_required": true,
    "code": "STORAGE_LIMIT_EXCEEDED",
    "error_code": "STORAGE_LIMIT_EXCEEDED",
    "message": "Storage limit reached. You have 429.15 MB available, but requested upload is 1144.41 MB.",
    "available_bytes": 450000000,
    "requested_bytes": 1200000000
  }
  ```
- **No Files Provided (`HTTP 400 Bad Request`):**
  ```json
  {
    "error": "No files provided. Send files under 'photos', 'videos', or 'files'.",
    "code": "NO_FILES_PROVIDED",
    "detail": "No files provided. Send files under 'photos', 'videos', or 'files'."
  }
  ```

---

### 4.2 Move Media Items Between Sections (`POST /api/galleries/{gallery_id}/media/move-section/`)
Allows moving multiple selected media items to an existing or new section in bulk. Automatically adds `target_section` to the gallery's `sections` array if not already present.

- **Content-Type:** `application/json` (or `multipart/form-data`)

**Request Body (`application/json`):**
```json
{
  "media_ids": [
    "c1f7b9de-2c6e-4735-86aa-cf615174092b",
    "d2f8a8ce-1b5d-4824-95bb-de726285183c"
  ],
  "target_section": "RECEPTION"
}
```

**Success Response (`HTTP 200 OK`):**
```json
{
  "status": "success",
  "message": "Successfully moved 2 media items to section RECEPTION.",
  "updated_count": 2,
  "section": "RECEPTION",
  "sections": ["HIGHLIGHTS", "CEREMONY", "RECEPTION"]
}
```

---

### 4.3 Direct-to-Storage Presigned Uploads (Optional Alternative)
Used when the client wants to upload directly to S3 / Cloudflare R2 without routing heavy multi-gigabyte payloads through the Django application server.

#### Step 1: Initialize Upload (`POST /api/galleries/{gallery_id}/upload-init/`)
Reserves storage quota atomically and returns pre-signed S3/R2 direct upload URLs.

**Request Body (`application/json`):**
```json
{
  "files": [
    {
      "filename": "drone_footage_4k.mp4",
      "file_size": 524288000,
      "mime_type": "video/mp4",
      "media_type": "video"
    }
  ]
}
```

**Response (`HTTP 200 OK`):**
```json
{
  "status": "success",
  "files": [
    {
      "reservation_id": "78648356-91e8-4ee4-bbf5-671e30a575a7",
      "storage_key": "galleries/29a3f20d/originals/78648356_drone_footage_4k.mp4",
      "filename": "drone_footage_4k.mp4",
      "media_type": "video",
      "upload_url": "https://s3.amazonaws.com/your-bucket/galleries/29a3f20d/...",
      "method": "PUT",
      "headers": {
        "Content-Type": "video/mp4"
      },
      "expires_in": 1800
    }
  ]
}
```

#### Step 2: Upload File Directly to Storage
Client executes HTTP `PUT` to `upload_url` with the binary file data and matching `Content-Type`.

#### Step 3: Confirm Upload (`POST /api/galleries/{gallery_id}/upload-confirm/`)
Validates file presence in storage, commits quota, and registers the `Media` item.

**Request Body (`application/json`):**
```json
{
  "reservation_id": "78648356-91e8-4ee4-bbf5-671e30a575a7",
  "storage_key": "galleries/29a3f20d/originals/78648356_drone_footage_4k.mp4",
  "original_filename": "drone_footage_4k.mp4",
  "file_size": 524288000,
  "mime_type": "video/mp4",
  "media_type": "video"
}
```

---

## 5. Media Organization & Action Endpoints

| Endpoint | Method | Payload / Parameters | Purpose |
| :--- | :--- | :--- | :--- |
| `/api/galleries/{gallery_id}/set-cover/` | `POST` | `{"media_id": "<uuid>"}` | Sets the primary cover image for client gallery cards and share previews. |
| `/api/galleries/{gallery_id}/reorder-media/` | `POST` | `{"ordered_ids": ["<uuid1>", "<uuid2>"]}` | Reorders photo grid display sequence. |
| `/api/galleries/{gallery_id}/template/` | `POST` | `{"template_id": "masonry"}` | Switches editorial template (`editorial`, `masonry`, `cinematic`, `minimal`). Checks plan permissions. |
| `/api/galleries/media/{media_id}/favorite/` | `POST` | *(Empty)* | Toggles `is_favorite` boolean on a photo. |
| `/api/galleries/media/{media_id}/` | `DELETE` | *(Empty)* | Permanently soft-deletes media item and frees up allocated storage bytes. |
| `/api/galleries/media/bulk-delete/` | `POST` | `{"media_ids": ["<uuid1>", "<uuid2>"]}` | Batch deletes multiple photos and recalculates storage quota. |
| `/api/galleries/{gallery_id}/share/` | `POST` | `{"action": "create"}` | Generates or fetches cryptographically secure public client share token and URL. |
| `/api/galleries/{gallery_id}/face-search/` | `POST` | Multipart `selfie: File` | AI biometric face search: returns matching photos strictly isolated within this gallery. |
| `/api/galleries/{gallery_id}/bulk-download/` | `POST` | `{"selection": "all"}` or `{"media_ids": [...]}` | Creates asynchronous master high-res ZIP export job. |
| `/api/galleries/bulk-download-jobs/{job_id}/` | `GET` | *(Empty)* | Polls ZIP generation progress (`pending` ➔ `processing` ➔ `ready`). |

---

## 6. Complete Frontend API Service Implementation (`src/service/galleries/GalleryApi.ts`)

```typescript
import { axiosInstance } from '@/lib/axiosInstance';
import type {
  Gallery,
  MediaItem,
  GalleryFilterParams,
  BatchUploadResponse,
  GalleryTemplateId,
} from '@/types/gallery';

// ---------------------------------------------------------------------------
// 1. Gallery CRUD & Status Switching
// ---------------------------------------------------------------------------

/** Get galleries with server-side filtering, searching, and sorting */
export const GetGalleriesApi = async (params?: GalleryFilterParams): Promise<Gallery[]> => {
  const res = await axiosInstance.get<Gallery[]>('/galleries/', { params });
  return res.data;
};

/** Get gallery detail including all media items */
export const GetGalleryDetailApi = async (idOrSlug: string): Promise<Gallery> => {
  const res = await axiosInstance.get<Gallery>(`/galleries/${idOrSlug}/`);
  return res.data;
};

/** Create a new client gallery (validates plan quotas) */
export const CreateGalleryApi = async (payload: {
  title: string;
  client_name?: string;
  client_email?: string;
  event_date?: string;
  template_id?: GalleryTemplateId;
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

/** Soft-delete / archive gallery */
export const DeleteGalleryApi = async (galleryId: string): Promise<void> => {
  await axiosInstance.delete(`/galleries/${galleryId}/`);
};

// ---------------------------------------------------------------------------
// 2. High-Capacity Media Uploads
// ---------------------------------------------------------------------------

/**
 * Standard & Batch Media Upload (supports up to 2,000+ files / 10 GB per request)
 * Handles onUploadProgress for accurate real-time UI progress bars.
 */
export const UploadGalleryMediaApi = async (
  galleryId: string,
  files: File[],
  sectionTitle?: string,
  onProgress?: (percent: number) => void
): Promise<BatchUploadResponse> => {
  const formData = new FormData();
  files.forEach((file) => formData.append('photos', file));

  if (sectionTitle) {
    formData.append('section_title', sectionTitle);
  }

  const res = await axiosInstance.post<BatchUploadResponse>(
    `/galleries/${galleryId}/upload/`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000, // 5 minutes for large batches
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }
  );

  return res.data;
};

// ---------------------------------------------------------------------------
// 3. Media Actions (Cover, Delete, Reorder, Template)
// ---------------------------------------------------------------------------

/** Set primary cover photo */
export const SetGalleryCoverApi = async (
  galleryId: string,
  mediaId: string
): Promise<{ cover_image: string }> => {
  const res = await axiosInstance.post(`/galleries/${galleryId}/set-cover/`, {
    media_id: mediaId,
  });
  return res.data;
};

/** Reorder gallery photo grid */
export const ReorderGalleryMediaApi = async (
  galleryId: string,
  orderedIds: string[]
): Promise<{ status: string }> => {
  const res = await axiosInstance.post(`/galleries/${galleryId}/reorder-media/`, {
    ordered_ids: orderedIds,
  });
  return res.data;
};

/** Switch gallery editorial template */
export const SwitchGalleryTemplateApi = async (
  galleryId: string,
  templateId: GalleryTemplateId
): Promise<{ status: string; template_id: GalleryTemplateId }> => {
  const res = await axiosInstance.post(`/galleries/${galleryId}/template/`, {
    template_id: templateId,
  });
  return res.data;
};

/** Toggle photo favorite state */
export const ToggleMediaFavoriteApi = async (mediaId: string): Promise<{ is_favorite: boolean }> => {
  const res = await axiosInstance.post(`/galleries/media/${mediaId}/favorite/`);
  return res.data;
};

/** Move photos/videos into another section in bulk */
export const MoveMediaToSectionApi = async (
  galleryId: string,
  mediaIds: string[],
  targetSection: string
): Promise<MoveMediaSectionResponse> => {
  const res = await axiosInstance.post<MoveMediaSectionResponse>(
    `/galleries/${galleryId}/media/move-section/`,
    {
      media_ids: mediaIds,
      target_section: targetSection,
    }
  );
  return res.data;
};

/** 
 * Delete a single photo or media item in a gallery:
 * Supports:
 *   - DELETE /api/galleries/{galleryId}/media/{mediaId}/
 *   - DELETE /api/galleries/{galleryId}/photos/{photoId}/
 *   - DELETE /api/galleries/media/{mediaId}/
 */
export const DeleteGalleryMediaApi = async (
  galleryId: string,
  mediaId: string
): Promise<{ status: string; message: string; deleted_id: string }> => {
  const res = await axiosInstance.delete(`/galleries/${galleryId}/media/${mediaId}/`);
  return res.data;
};

/** Direct media delete by mediaId */
export const DeleteMediaApi = async (mediaId: string): Promise<{ message: string; deleted_id: string }> => {
  const res = await axiosInstance.delete(`/galleries/media/${mediaId}/`);
  return res.data;
};

/** Bulk delete multiple media items from gallery */
export const BulkDeleteMediaApi = async (
  galleryId: string,
  mediaIds: string[]
): Promise<{ deleted_count: number; freed_bytes: number }> => {
  const res = await axiosInstance.delete(`/galleries/${galleryId}/media/bulk-delete/`, {
    data: { media_ids: mediaIds },
  });
  return res.data;
};
```

---

## 7. React Upload Component with Progress Bar Example

```tsx
import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { UploadGalleryMediaApi } from '@/service/galleries/GalleryApi';

interface UploadDropzoneProps {
  galleryId: string;
  sectionTitle?: string;
}

export const GalleryUploadDropzone: React.FC<UploadDropzoneProps> = ({ galleryId, sectionTitle }) => {
  const queryClient = useQueryClient();
  const [uploadPercent, setUploadPercent] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) =>
      UploadGalleryMediaApi(galleryId, files, sectionTitle, (percent) => setUploadPercent(percent)),
    onSuccess: (data) => {
      setUploadPercent(0);
      setErrorMessage(null);
      // Invalidate gallery details and subscription quota caches
      queryClient.invalidateQueries({ queryKey: ['gallery', galleryId] });
      queryClient.invalidateQueries({ queryKey: ['current-subscription'] });
    },
    onError: (error: any) => {
      setUploadPercent(0);
      const data = error.response?.data;
      if (data?.code === 'STORAGE_LIMIT_EXCEEDED') {
        setErrorMessage(data.message || 'Storage limit reached. Please upgrade your plan.');
      } else if (data?.error) {
        setErrorMessage(data.error);
      } else {
        setErrorMessage('Failed to upload files. Please try again.');
      }
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFiles = Array.from(e.target.files);
      uploadMutation.mutate(selectedFiles);
    }
  };

  return (
    <div className="border-2 border-dashed border-neutral-700 rounded-xl p-8 text-center bg-neutral-900/40 hover:border-neutral-500 transition">
      <input
        type="file"
        multiple
        accept="image/*"
        onChange={handleFileChange}
        disabled={uploadMutation.isPending}
        className="hidden"
        id="bulk-file-upload"
      />
      <label htmlFor="bulk-file-upload" className="cursor-pointer">
        <div className="text-sm font-medium text-neutral-200">
          Click or drag & drop high-resolution photos here
        </div>
        <div className="text-xs text-neutral-500 mt-1">
          Supports JPG, PNG, WebP up to 10 GB per batch
        </div>
      </label>

      {uploadMutation.isPending && (
        <div className="mt-4">
          <div className="w-full bg-neutral-800 rounded-full h-2 overflow-hidden">
            <div
              className="bg-emerald-500 h-2 transition-all duration-300"
              style={{ width: `${uploadPercent}%` }}
            />
          </div>
          <div className="text-xs text-neutral-400 mt-2">Uploading: {uploadPercent}%</div>
        </div>
      )}

      {errorMessage && (
        <div className="mt-3 text-xs text-red-400 bg-red-950/40 border border-red-800/40 rounded-lg p-2">
          {errorMessage}
        </div>
      )}
    </div>
  );
};
```
