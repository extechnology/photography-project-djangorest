# Project Structure & Architecture Guide

> **Project Name:** EX SHARE / Atelier Backend (`photography-project-djangorest`)  
> **Framework:** Django 6.0.7 / Django REST Framework 3.17.1  
> **Asynchronous Engine:** Celery 5.6.3 with Redis broker & Celery Beat  
> **AI / Vision Pipeline:** OpenCV (YuNet face detection + SFace embeddings + Landmark geometry expression analysis)  
> **Payments & Subscriptions:** Razorpay Integration  
> **Storage Engine:** Local filesystem media storage with self-healing recovery and S3/cloud storage compatibility  

---

## 1. High-Level Architecture Overview

This project is a multi-tenant SaaS backend for professional photographers, studios, and event organizers. It provides:

1. **Authentication & Multi-Role User Management:** Custom user model supporting `Admin`, `Staff`, `Photographer`, and `User` roles with JWT authentication, Google OAuth, and SMS/Email passwordless OTP.
2. **Gallery & Cloud Storage Engine:** High-performance media storage, client access links, PIN/password protection, dynamic watermarking, favorites, client selection pipelines, ZIP downloads, and self-healing media recovery.
3. **AI Face Recognition & Search:** YuNet face detection and SFace 128-dimensional embedding generation. Enables instant visitor face-search in galleries and live event photos.
4. **AI Culling Engine:** Automated photo staging, burst sequence clustering, facial landmark & expression detection (eyes open/closed, smile/mouth state), blur/quality scoring, keeper selection, and automated gallery migration.
5. **Live Events Engine:** Real-time event photo streaming, attendee selfie face matching, QR code distribution, and auto-purge trash management.
6. **Studio Portfolio & Inquiry CRM:** Public portfolio showcases, multi-template configurations, visitor tracking telemetry, and client lead/inquiry CRM pipeline.
7. **Tiered Subscriptions & Billing:** Studio plans (Free, Pro, Studio, Enterprise), automated quota enforcement, storage add-ons, Razorpay checkout, and webhook verification.

```
                    ┌────────────────────────────────────────────────────────┐
                    │                  Client Applications                   │
                    │        (Web Dashboard, Public Gallery, Studio Site)    │
                    └──────────────────────────┬─────────────────────────────┘
                                               │ HTTP / REST APIs
                                               ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                    Django REST Framework                                  │
│                                                                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │    App.Auth      │  │   App.Storage    │  │   culling App    │  │  App.LiveEvents   │  │
│  │  (JWT/OTP/User)  │  │ (Galleries/Media)│  │ (AI Culling/Clust│  │ (Live QR/Selfie)  │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  └───────────────────┘  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │ App.Photographers│  │App.Subscriptions │  │    portfolio     │  │backend/atelier... │  │
│  │ (Profiles/Posts) │  │(Plans/Razorpay)  │  │(Showcases/Inquiry│  │(Notifs & Billing) │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  └───────────────────┘  │
│                                               │                                           │
│                       ┌───────────────────────┴───────────────────────┐                   │
│                       │    App.face_engine (YuNet + SFace ONNX)       │                   │
│                       └───────────────────────┬───────────────────────┘                   │
└───────────────────────────────────────────────┼───────────────────────────────────────────┘
                                                │ Async Tasks
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │       Celery Workers + Redis Broker          │
                         │  - Media transformation & watermarks         │
                         │  - Face indexing & embeddings extraction     │
                         │  - AI Culling photo analysis                 │
                         │  - Zip exports & Storage reconciliation      │
                         └──────────────────────────────────────────────┘
```

---

## 2. Complete Project Directory Tree

Below is the directory structure of the repository (excluding runtime cache files, virtual environment, and uploaded raw images):

```
photography-project-djangorest/
├── .env                                       # Environment configuration (secrets, keys, database, Redis)
├── .env.example                               # Template for environment configuration
├── .gitignore                                 # Git ignore patterns
├── manage.py                                  # Django CLI management script
├── README.md                                  # Repository overview
├── requirements.txt                           # Python package dependencies
├── db.sqlite3                                 # Local SQLite database (development)
├── celerybeat-schedule.bak                    # Celery beat periodic schedule state (backup)
├── celerybeat-schedule.dat                    # Celery beat periodic schedule state (data)
├── celerybeat-schedule.dir                    # Celery beat periodic schedule state (dir)
│
├── config/                                    # Django Project Configuration & Root Routing
│   ├── __init__.py
│   ├── asgi.py                                # ASGI asynchronous gateway interface
│   ├── celery.py                              # Celery app initialization & broker setup
│   ├── settings.py                            # Master Django settings (CORS, apps, auth, DB, media)
│   ├── urls.py                                # Root URL router + Resilient media self-healing engine
│   └── wsgi.py                                # WSGI production web server gateway
│
├── App/                                       # Core Unified Application Package
│   ├── __init__.py
│   ├── admin.py                               # Unified admin registrations
│   ├── apps.py                                # AppConfig definition
│   ├── face_engine.py                         # OpenCV YuNet & SFace face detection + landmarks engine
│   ├── models.py                              # Master aggregator re-exporting all sub-domain models
│   ├── tasks.py                               # Global async Celery tasks
│   ├── tests.py                               # App-wide test cases
│   ├── urls.py                                # Main API router connecting all sub-domains
│   ├── utils.py                               # Shared domain utility functions
│   ├── views.py                               # Common views
│   │
│   ├── ai_models/                             # Neural network ONNX weights for local inference
│   │   ├── face_detection_yunet_2023mar.onnx  # YuNet face detector model
│   │   └── face_recognition_sface_2021dec.onnx# SFace 128D embedding generator model
│   │
│   ├── Auth/                                  # Authentication & User Management Domain
│   │   ├── __init__.py
│   │   ├── auth_admins.py                     # Django admin for User and OTP models
│   │   ├── auth_backend.py                    # Custom authentication backend (Email/Phone/Username)
│   │   ├── auth_emails.py                     # Email sending helpers & async Celery tasks
│   │   ├── auth_models.py                     # Custom User, RegistrationOTP, PasswordlessLoginOTP
│   │   ├── auth_serializers.py                # Serializers for login, registration, OTP, JWT tokens
│   │   ├── auth_urls.py                       # Route definitions for /api/auth/
│   │   ├── auth_utils.py                      # OTP token generation and verification logic
│   │   └── auth_views.py                      # View endpoints (JWT, Google auth, passwordless, OTP)
│   │
│   ├── Storage/                               # Storage, Galleries & Media Lifecycle Domain
│   │   ├── __init__.py
│   │   ├── models.py                          # Proxy module
│   │   ├── permissions.py                     # Gallery access permissions (Owner, Client PIN/Pass)
│   │   ├── serializers.py                     # Gallery serializers compatibility layer
│   │   ├── storage_admins.py                  # Django admin for Galleries, Media, Selections
│   │   ├── storage_models.py                  # Models: Gallery, Media, GallerySection, FaceEmbedding,
│   │   │                                      # BulkDownloadJob, GalleryClientSelection, etc.
│   │   ├── storage_serializers.py             # Serializers for galleries, photos, watermarks, selections
│   │   ├── storage_urls.py                    # Routes for /api/storage/ and /api/galleries/
│   │   ├── storage_views.py                   # Gallery CRUD, upload reservation, face search, PIN auth
│   │   ├── tasks.py                           # Celery tasks: watermark processing, ZIP creation, face index
│   │   ├── throttling.py                      # Rate limiting policies for media & search endpoints
│   │   ├── views.py                           # Storage views compatibility layer
│   │   ├── management/
│   │   │   └── commands/
│   │   │       └── reconcile_storage_usage.py # Command to recalculate storage bytes per photographer
│   │   ├── services/                          # Specialized Business Logic Services
│   │   │   ├── __init__.py
│   │   │   ├── face_service.py                # YuNet/SFace extraction & cosine distance vector match
│   │   │   ├── media_transfer.py              # Photo movement & transformation between buckets/folders
│   │   │   ├── quota_service.py               # Storage quota checks and limits enforcement
│   │   │   ├── storage_service.py             # File saving, thumbnail generation, hash calculation
│   │   │   └── watermark_service.py           # Pillow-based dynamic image watermarking engine
│   │   └── tests/                             # Test Suite for Storage & Galleries
│   │       ├── __init__.py
│   │       ├── fixtures/                      # Test sample images for face matching
│   │       │   ├── no_face.jpg
│   │       │   ├── person1_face.jpg
│   │       │   ├── person1_selfie.jpg
│   │       │   └── person2_face.jpg
│   │       ├── test_enterprise_storage.py
│   │       ├── test_event_storage.py
│   │       ├── test_face_engine.py
│   │       ├── test_gallery_atelier_balanced_apis.py
│   │       ├── test_gallery_bulk_delete_and_counts.py
│   │       ├── test_gallery_cursor_pagination.py
│   │       ├── test_gallery_expiration_and_access_window.py
│   │       ├── test_gallery_face_search_and_password.py
│   │       ├── test_gallery_media_reorder.py
│   │       ├── test_gallery_status_filtering.py
│   │       ├── test_gallery_zip_download.py
│   │       └── test_watermark.py
│   │
│   ├── LiveEvents/                            # Real-time Live Event Photo Streaming & Selfie Search
│   │   ├── __init__.py
│   │   ├── event_admins.py                    # Django admin for Live Events & Event Media
│   │   ├── event_models.py                    # Models: LiveEvent, EventMedia, EventFaceEmbedding
│   │   ├── event_serializers.py               # Serializers for live events, attendee views, media
│   │   ├── event_tasks.py                     # Celery tasks: process event embeddings, selfie search
│   │   ├── event_urls.py                      # Routes for /api/events/ and /api/public/events/
│   │   ├── event_views.py                     # Event creation, photo stream, selfie face search
│   │   ├── tasks.py                           # Event tasks alias
│   │   └── tests/                             # Live Events Test Suite
│   │       ├── __init__.py
│   │       ├── test_bulk_delete_and_counts.py
│   │       ├── test_event_update.py
│   │       ├── test_live_events.py
│   │       └── test_storage_metrics.py
│   │
│   ├── Culling/                               # In-App Culling Workflows & Gallery Bridges
│   │   ├── __init__.py
│   │   ├── culling_models.py                  # Models: CullingSession, CullingClusterGroup, CullingItem
│   │   ├── culling_serializers.py             # Serializers for culling sessions and items
│   │   ├── culling_urls.py                    # Routes for /api/culling/ in App module
│   │   ├── culling_views.py                   # Session views, keeper selections, bridge triggers
│   │   ├── tasks.py                           # Celery async culling processing tasks
│   │   ├── services/                          # Specialized Culling Services
│   │   │   ├── __init__.py
│   │   │   ├── culler.py                      # AI scoring and duplicate grouping logic
│   │   │   ├── culling_engine.py              # Clustering and similarity evaluation engine
│   │   │   ├── gallery_bridge.py              # Moving culled keepers into storage Gallery models
│   │   │   ├── move_service.py                # File relocation and storage quota transfers
│   │   │   ├── payment.py                     # Culling payment validation
│   │   │   └── payment_service.py             # Razorpay order generation for culling
│   │   └── tests/                             # Culling In-App Test Suite
│   │       ├── __init__.py
│   │       ├── test_culling_workflow.py
│   │       └── test_upfront_payment_and_purge.py
│   │
│   ├── Photographers/                         # Photographer Profile, Portfolio & Social Domain
│   │   ├── __init__.py
│   │   ├── photo_admins.py                    # Django admin for profiles, posts, categories
│   │   ├── photo_emails.py                    # Photographer notification emails
│   │   ├── photo_models.py                    # Models: PhotographerProfile, PhotoCategory,
│   │   │                                      # PhotographerPost, PostImage, PostFeedback, Inquiry
│   │   ├── photo_serializers.py               # Profile serializers, onboarding, social posts
│   │   ├── photo_urls.py                      # Routes for /api/photographers/
│   │   ├── photo_utils.py                     # Nudity/NSFW detection check (NudeNet) & avatar helpers
│   │   ├── photo_views.py                     # Profile management, onboarding, inquiries, posts
│   │   ├── test_nude_detection.py             # NSFW content moderation test
│   │   └── test_onboarding_flow.py            # Photographer onboarding lifecycle test
│   │
│   ├── Subscriptions/                         # Tiered Plans, Quotas & Razorpay Billing Domain
│   │   ├── __init__.py
│   │   ├── sub_admins.py                      # Django admin for Plans & Subscriptions
│   │   ├── sub_enforcer.py                    # Quota enforcement middleware and helper functions
│   │   ├── sub_models.py                      # Models: Plan, PhotographerSubscription, SubscriptionPayment
│   │   ├── sub_serializers.py                 # Serializers for plans, active subscriptions, checkout
│   │   ├── sub_services.py                    # Plan limits validation and subscription renewal logic
│   │   ├── sub_urls.py                        # Routes for /api/plans/ and /api/subscriptions/
│   │   ├── sub_views.py                       # Plans list, checkout, Razorpay verify, upgrade, cancel
│   │   ├── tasks.py                           # Celery task for periodic subscription expiry check
│   │   ├── views_razorpay.py                  # Direct Razorpay webhook and payment callbacks
│   │   └── tests/                             # Subscriptions Test Suite
│   │       ├── __init__.py
│   │       ├── test_studio_plans.py
│   │       ├── test_subscription_enforcement.py
│   │       └── test_subscription_expiry_lock.py
│   │
│   ├── Notifications/                         # Studio Notifications Domain
│   │   ├── __init__.py
│   │   ├── tests.py                           # Notification tests
│   │   ├── urls.py                            # Notification routes
│   │   └── views.py                           # Notification list, read, clear views
│   │
│   ├── management/                            # Custom Django Management Commands
│   │   ├── __init__.py
│   │   └── commands/
│   │       ├── __init__.py
│   │       ├── purge_expired_trash_events.py  # Cleans deleted events older than 30 days
│   │       ├── reconcile_storage_usage.py     # Re-indexes actual disk storage bytes vs database
│   │       ├── reindex_faces.py               # Re-generates YuNet & SFace embeddings for media
│   │       ├── repair_server_gallery_media.py # Resolves broken media file paths and regenerates thumbs
│   │       ├── seed_plans.py                  # Seeds baseline pricing and quota plans
│   │       ├── seed_studio_plans.py           # Seeds studio plans (Free, Pro, Studio, Enterprise)
│   │       └── test_face_engine.py            # CLI benchmark testing YuNet & SFace face accuracy
│   │
│   └── migrations/                            # Database schema migrations for `App`
│       ├── 0001_initial.py ... 0040_plan_ai_culling_enabled_and_more.py
│       └── __init__.py
│
├── culling/                                   # Standalone AI Culling Micro-Application
│   ├── __init__.py
│   ├── admin.py                               # Admin for CullingSession, CullingStagingPhoto, CullingCluster
│   ├── ai_engine.py                           # Core AI Pipeline: image hash, blur scoring, face landmark detection,
│   │                                          # eye state, mouth/smile expressions, and cluster grouping
│   ├── apps.py                                # AppConfig for culling app
│   ├── models.py                              # Models: CullingPricingTier, CullingSession,
│   │                                          # CullingStagingPhoto (with face_analysis), CullingCluster
│   ├── permissions.py                         # Culling session access controls
│   ├── serializers.py                         # Culling session & photo serializers
│   ├── tasks.py                               # Celery tasks: background AI photo processing
│   ├── urls.py                                # Routes for /api/culling/ (upload, analyze, sync, move, export)
│   ├── views.py                               # View controllers for staging, AI analysis, move-to-gallery
│   ├── management/
│   │   ├── __init__.py
│   │   └── commands/
│   │       ├── __init__.py
│   │       ├── cleanup_stale_culling.py       # Garbage collector for abandoned staging sessions
│   │       └── seed_culling_plans.py          # Seeds culling pricing tiers
│   ├── migrations/
│   │   ├── 0001_initial.py ... 0005_add_face_analysis_field.py
│   │   └── __init__.py
│   ├── services/                              # Services mirror for independent culling operations
│   │   ├── __init__.py
│   │   ├── culler.py
│   │   ├── culling_engine.py
│   │   ├── gallery_bridge.py
│   │   ├── move_service.py
│   │   ├── payment.py
│   │   └── payment_service.py
│   └── tests/
│       ├── __init__.py
│       └── test_lifecycle.py
│
├── portfolio/                                 # Public Portfolio & Client Lead CRM Application
│   ├── __init__.py
│   ├── admin.py                               # Admin for PortfolioConfig, PortfolioWork, Inquiries
│   ├── apps.py                                # AppConfig for portfolio
│   ├── models.py                              # Models: PortfolioConfig, PortfolioWork, PortfolioWorkPhoto,
│   │                                          # PortfolioInquiry, PortfolioView
│   ├── serializers.py                         # Serializers for branding config, showcase works, inquiries
│   ├── urls.py                                # Routes for /api/portfolio/ and /api/public/portfolio/
│   ├── utils.py                               # Portfolio utilities (slug generators, image helpers)
│   ├── views.py                               # Portfolio showcase, project photo gallery, analytics, CRM
│   ├── migrations/
│   │   ├── 0001_initial.py ... 0004_alter_portfolioconfig_template_id.py
│   │   └── __init__.py
│   └── tests/
│       ├── __init__.py
│       └── test_portfolio_lifecycle.py
│
├── gallery/                                   # Gallery Feature Additions (Reorder & Story Videos)
│   ├── __init__.py
│   ├── models.py                              # Compatibility re-export from App.Storage.storage_models
│   ├── serializers.py                         # Reorder and StoryVideo serializers
│   ├── tasks.py                               # Celery tasks for video processing
│   ├── urls.py                                # Routes for reorder, story videos, guest sessions
│   ├── views.py                               # GalleryViewSet (reorder_media), StoryVideo views
│   ├── services/
│   │   ├── __init__.py
│   │   └── reorder.py                         # Drag-and-drop media ordering algorithms
│   └── tests/
│       ├── __init__.py
│       ├── test_reorder.py
│       └── test_story_videos.py
│
├── galleries/                                 # Backward-Compatibility Shim Module
│   ├── __init__.py
│   ├── models.py                              # Re-exports Gallery, Media, GallerySection
│   ├── serializers.py                         # Re-exports storage serializers
│   └── tests/
│       ├── __init__.py
│       └── test_watermark.py
│
├── backend/                                   # Auxiliary Backend Packages
│   ├── atelier_notifications/                 # Studio Notification Views & Routes
│   │   ├── __init__.py
│   │   ├── urls.py
│   │   └── views.py
│   ├── atelier_plans/                         # Plan Enforcement & Payment Helpers
│   │   ├── subscription_enforcement.py
│   │   └── views_razorpay.py
│   └── billing/                               # Billing & Public Gallery Route Shims
│       ├── __init__.py
│       ├── urls.py
│       └── views.py
│
├── subscriptions/                             # Backward-Compatibility Shim for Subscriptions
│   ├── __init__.py
│   ├── models.py                              # Re-exports Plan, PhotographerSubscription
│   └── serializers.py                         # Re-exports subscription serializers
│
├── face_models/                               # Standalone Face Recognition ONNX Model Storage
│   ├── face_detection_yunet_2023mar.onnx      # OpenCV YuNet Face Detection ONNX
│   └── face_recognition_sface_2021dec.onnx    # OpenCV SFace 128D Face Recognition ONNX
│
├── utils/                                     # Global Shared Utilities
│   ├── __init__.py
│   └── watermark.py                           # Low-level PIL watermark rendering functions
│
├── templates/                                 # Server-rendered HTML Templates
│   └── profile_preview.html                   # HTML preview template for photographer profile
│
└── media/                                     # Runtime File Storage Directory (Local Media Root)
    ├── storage_objects/                       # Permanent media stored by galleries
    │   ├── galleries/<gallery_uuid>/originals/
    │   ├── galleries/<gallery_uuid>/previews/
    │   └── galleries/<gallery_uuid>/thumbnails/
    ├── culling_staging/                       # Staging directory for ongoing culling sessions
    │   └── <session_id>/
    ├── events/                                # Live events media, photos, and thumbnails
    │   ├── media/
    │   ├── photos/
    │   └── thumbs/
    ├── photographer_profiles/                 # Uploaded photographer avatars and cover photos
    ├── portfolio_photos/                      # Featured portfolio work highlight photos
    └── post_images/                           # Photographer feed post attachments
```

---

## 3. Database Models & Schema Matrix

| App / Domain | Model Name | Primary Key | Key Relationships | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Auth** | `User` | `AutoField` (int) + `unique_id` (UUID) | None | Custom user with roles: Admin, Staff, Photographer, User. |
| **Auth** | `RegistrationOTP` | `AutoField` | - | OTP verification during registration. |
| **Auth** | `ResetPasswordOTP` | `AutoField` | - | OTP verification for password resets. |
| **Auth** | `PasswordlessLoginOTP` | `AutoField` | - | Passwordless OTP login for users/clients. |
| **Photographers** | `PhotoCategory` | `AutoField` | - | Categorization for photography genres (Wedding, Portrait, etc.). |
| **Photographers** | `PhotographerProfile`| `AutoField` | `OneToOne(User)` | Bio, studio name, storage bytes used/reserved, watermark config. |
| **Photographers** | `NotificationPreference`| `AutoField` | `OneToOne(User)` | Email and push notification toggles. |
| **Photographers** | `PhotographerPost` | `AutoField` | `ForeignKey(User)` | Social feed updates and portfolio updates. |
| **Photographers** | `PostImage` | `AutoField` | `ForeignKey(PhotographerPost)` | Attached photos to a photographer feed post. |
| **Photographers** | `PostFeedback` | `AutoField` | `ForeignKey(PhotographerPost)` | Client feedback/comments on posts. |
| **Photographers** | `Inquiry` | `AutoField` | `ForeignKey(PhotographerProfile)`| Client booking inquiries and leads. |
| **Subscriptions** | `Plan` / `SubscriptionPlans` | `AutoField` | - | Pricing tiers: Free, Pro, Studio, Enterprise, storage limits, features. |
| **Subscriptions** | `PhotographerSubscription`| `AutoField` | `ForeignKey(User)`, `ForeignKey(Plan)` | Active subscription record, renewal date, status. |
| **Subscriptions** | `SubscriptionPayment` | `AutoField` | `ForeignKey(User)`, `ForeignKey(Plan)` | Razorpay transaction records, order IDs, payment signatures. |
| **Storage** | `Gallery` | `UUIDField` | `ForeignKey(User)` | Photo gallery with client PIN, password, watermark toggles, expiry. |
| **Storage** | `GallerySection` | `CharField` / `UUIDField` | `ForeignKey(Gallery)` | Categorized albums/sections within a gallery (e.g., Reception, Haldi). |
| **Storage** | `Media` | `UUIDField` | `ForeignKey(Gallery)`, `ForeignKey(GallerySection)` | Uploaded photos/videos, original/preview/thumb paths, size, order. |
| **Storage** | `FaceEmbedding` | `UUIDField` | `ForeignKey(Media)` | 128-dimensional vector embedding of detected faces in gallery media. |
| **Storage** | `GalleryClientSelection` | `UUIDField` | `ForeignKey(Gallery)` | Client favorite selections and album approval submissions. |
| **Storage** | `BulkDownloadJob` | `UUIDField` | `ForeignKey(Gallery)` | Asynchronous Celery job state for generating full-gallery ZIP downloads. |
| **Storage** | `GalleryGuestSession` | `UUIDField` | `ForeignKey(Gallery)` | Public guest viewing session and favorites tracking. |
| **Storage** | `GalleryStoryVideo` | `UUIDField` | `ForeignKey(Gallery)` | Vertical reel/story videos attached to client gallery. |
| **LiveEvents** | `LiveEvent` | `UUIDField` | `ForeignKey(User)` | Real-time event coverage session with QR code & selfie matching. |
| **LiveEvents** | `EventMedia` | `UUIDField` | `ForeignKey(LiveEvent)` | Photos uploaded live to the event stream. |
| **LiveEvents** | `EventFaceEmbedding` | `UUIDField` | `ForeignKey(EventMedia)` | Face embeddings for fast attendee selfie face lookup. |
| **culling** | `CullingPricingTier` | `CharField` (code) | - | Pricing tiers for culling credit usage. |
| **culling** | `CullingSession` | `CharField` (session_id) | `ForeignKey(User)` | In-progress AI culling session (burst detection, curation). |
| **culling** | `CullingStagingPhoto` | `UUIDField` | `ForeignKey(CullingSession)` | Staged photo with blur score, face analysis (eyes/mouth), keeper state. |
| **culling** | `CullingCluster` | `CharField` (id) | `ForeignKey(CullingSession)` | Burst shot clusters grouping visually similar photos. |
| **portfolio** | `PortfolioConfig` | `AutoField` | `OneToOne(PhotographerProfile)` | Studio branding, selected template, social links, custom domains. |
| **portfolio** | `PortfolioWork` | `AutoField` | `ForeignKey(PortfolioConfig)` | Featured project showcase item. |
| **portfolio** | `PortfolioWorkPhoto` | `AutoField` | `ForeignKey(PortfolioWork)` | Photos attached to a showcase project. |
| **portfolio** | `PortfolioInquiry` | `AutoField` | `ForeignKey(PortfolioConfig)` | Inquiries submitted directly through the public portfolio website. |
| **portfolio** | `PortfolioView` | `AutoField` | `ForeignKey(PortfolioConfig)` | Daily telemetry and visitor count analytics. |

---

## 4. Master API Route Map

### 4.1 Authentication (`/api/auth/`)
- `POST /api/auth/register/` — Register user / photographer
- `POST /api/auth/login/` — Standard username/email + password login (JWT response)
- `POST /api/auth/logout/` — Blacklist refresh token & logout
- `POST /api/auth/token/refresh/` — Refresh access token
- `POST /api/auth/google/` — Google OAuth2 authentication
- `POST /api/auth/check-username/` & `POST /api/auth/check-identifier/` — Identifier availability checks
- `POST /api/auth/resend-otp/` & `POST /api/auth/verify-otp/` — Email/SMS OTP verification
- `POST /api/auth/passwordless/login/send-otp/` — Send passwordless login code
- `POST /api/auth/passwordless/login/verify-otp/` — Verify code and receive JWT
- `POST /api/auth/reset-password/otp/` & `verify-otp/` — Password recovery flow

### 4.2 Galleries & Storage Engine (`/api/galleries/` & `/api/storage/`)
- `GET|POST /api/galleries/` — List & create galleries
- `GET|PUT|PATCH|DELETE /api/galleries/<gallery_id>/` — Gallery management
- `POST /api/galleries/<gallery_id>/restore/` — Restore soft-deleted gallery
- `GET|POST /api/galleries/<gallery_id>/media/` — List and batch-upload gallery media
- `DELETE /api/galleries/media/bulk-delete/` — Batch deletion of media items
- `POST /api/galleries/<gallery_id>/media/reorder/` — Update display sequence of photos
- `POST /api/galleries/<gallery_id>/face-search/` — Search photos matching an uploaded selfie face
- `GET|POST /api/galleries/<gallery_id>/client-selections/` — Client photo selection & album approvals
- `POST /api/galleries/<gallery_id>/bulk-download/` — Trigger async ZIP compilation
- `GET /api/galleries/bulk-download-jobs/<job_id>/` — Poll ZIP compilation job status
- `GET /api/public/galleries/<slug_or_id>/` — Public client view of a gallery
- `POST /api/public/galleries/<slug_or_id>/verify-pin/` — Validate client PIN access
- `GET /api/account/storage/` — Photographer storage capacity & quota breakdown

### 4.3 AI Culling Engine (`/api/culling/`)
- `POST /api/culling/upload/` — Staging upload for burst photo sets
- `GET /api/culling/sessions/active/` — Retrieve currently active culling session
- `GET /api/culling/sessions/<session_id>/` — Fetch detailed session with clusters and scored photos
- `POST /api/culling/sessions/<session_id>/analyze/` — Trigger AI engine (blur, landmarks, eyes, smiles, clustering)
- `POST /api/culling/sessions/<session_id>/sync/` — Sync manual keeper/rejected selections from frontend
- `POST /api/culling/sessions/<session_id>/move-to-gallery/` — Migrate approved keepers into a permanent gallery
- `POST /api/culling/sessions/<session_id>/discard/` — Purge staging files and discard session
- `GET /api/culling/sessions/<session_id>/export-zip/` — Download keepers as a ZIP archive
- `GET /api/culling/plans/` & `pricing-tiers/` — Fetch culling credit tiers
- `POST /api/culling/checkout/order/` & `verify/` — Razorpay payment for culling credits

### 4.4 Live Events (`/api/events/` & `/api/public/events/`)
- `GET|POST /api/events/` — List & create live events
- `GET|PUT|DELETE /api/events/<event_id>/` — Manage live event details
- `POST /api/events/<event_id>/media/` — Stream uploads into live event
- `POST /api/events/<event_id>/face-search/` — Match attendee selfie to live event photos
- `GET /api/public/events/<id_or_slug>/` — Public attendee live gallery view

### 4.5 Portfolio & Studio CRM (`/api/portfolio/`)
- `GET|PUT /api/portfolio/config/` — Customize studio branding, theme, template, and socials
- `GET /api/portfolio/analytics/` — Real-time analytics (views, popular projects, visitor devices)
- `GET|POST /api/portfolio/projects/` — Portfolio showcase works management
- `GET|POST /api/portfolio/projects/<work_id>/photos/` — High-res showcase photos
- `POST /api/public/portfolio/<slug_or_id>/track-view/` — Public telemetry tracking
- `GET /api/public/portfolio/<photographer_slug>/` — Public portfolio showcase rendering
- `POST /api/public/inquiries/` — Public client inquiry submission
- `GET|PATCH|DELETE /api/inquiries/` — Studio inquiry CRM management pipeline

### 4.6 Subscriptions & Billing (`/api/subscriptions/` & `/api/plans/`)
- `GET /api/subscriptions/plans/` — View available studio subscription tiers
- `GET /api/subscriptions/current/` — Active subscription status and quota limits
- `POST /api/subscriptions/checkout/` — Create Razorpay subscription order
- `POST /api/subscriptions/verify/` — Verify Razorpay payment signature and activate plan
- `POST /api/subscriptions/cancel/` & `resume/` — Auto-renew cancellation and resumption
- `POST /api/subscriptions/storage-addon/` — Purchase extra GB storage add-on pack
- `POST /api/subscriptions/webhook/` — Razorpay webhook listener

---

## 5. Vision AI Engine Deep Dive (`App/face_engine.py` & `culling/ai_engine.py`)

The vision pipeline is self-contained using ONNX models running directly via OpenCV's `dnn` module:

```
[Uploaded Photo] ───► [Exif Transpose & Resize]
                              │
                              ▼
                 [YuNet Face Detector (ONNX)]
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
    [5-Point Landmarks]            [SFace Recognizer (ONNX)]
  (Eyes, Nose, Mouth Corners)                │
               │                             ▼
               ▼                  [128D Embedding Vector]
   [Geometric Calculations]                  │
  - Eye Openness (Aspect Ratio)              ▼
  - Smile Width & Expression Score   [Cosine Similarity Match]
  - Head Pose & Tilt Estimation      (Threshold ~ 0.363)
```

1. **Detection Model (`face_detection_yunet_2023mar.onnx`):**
   - Detects multiple human faces in a single frame with bounding boxes and 5 key facial landmarks.
2. **Recognition Model (`face_recognition_sface_2021dec.onnx`):**
   - Crops aligned face regions and outputs a normalized 128-dimensional feature embedding vector.
   - Vector distance comparison is performed via cosine distance (`1.0 - dot_product`). Distances below `0.363` represent a biometric match.
3. **Facial Expression & Landmark Analysis:**
   - Evaluates eye aspect ratios to determine if eyes are open or closed during a burst shot.
   - Evaluates mouth corner separation relative to inter-pupillary distance to score smile and expression quality.
4. **Blur Detection:**
   - Evaluates image sharpness using the Laplacian variance across gray-scale image channels.

---

## 6. Asynchronous Celery Tasks & Management Commands

### Celery Shared Tasks
- **`App.Storage.tasks.process_media_item_task`:** Generates Lanczos thumbnails (300x300) and web previews (1200x1200), calculates MD5/SHA hashes, and applies watermarks.
- **`App.Storage.tasks.index_media_faces_task`:** Runs YuNet and SFace over newly uploaded media and stores `FaceEmbedding` records in the database.
- **`App.Storage.tasks.build_bulk_download_zip_task`:** Zips high-resolution originals into a downloadable archive and notifies the user upon completion.
- **`App.Subscriptions.tasks.check_subscription_expiry_task`:** Daily scheduled task via Celery Beat that identifies expired subscriptions and transitions accounts to read-only lock.
- **`events.process_face_embeddings` & `events.compare_selfie_faces`:** Real-time event face indexing and selfie comparison jobs.
- **`culling.tasks.process_culling_session_task`:** Offloads heavy batch AI processing for culling sessions.

### CLI Management Commands
- `python manage.py seed_studio_plans` — Initializes baseline subscription plans (Free, Pro, Studio, Enterprise).
- `python manage.py reconcile_storage_usage` — Scans media files on disk and synchronizes accurate storage byte usage to each photographer profile.
- `python manage.py reindex_faces` — Re-runs face detection and embedding extraction across all gallery media.
- `python manage.py repair_server_gallery_media` — Checks for missing disk paths, creates missing thumbnails/previews, and repairs media records.
- `python manage.py test_face_engine` — Runs verification tests on YuNet and SFace using test fixture images.
- `python manage.py purge_expired_trash_events` — Permanently purges soft-deleted live events older than 30 days.
- `python manage.py cleanup_stale_culling` — Purges temporary culling staging directories for inactive sessions.

---

## 7. Media Self-Healing Engine (`config/urls.py`)

A unique resilience feature implemented in `config/urls.py` is the `try_recover_missing_media` handler. When requests to `/media/storage_objects/...` return a 404:
1. The server intercepts the request and inspects the database `Media` records by storage key, preview key, or UUID.
2. If the original high-resolution file exists in an alternate folder (e.g. `culling_staging/` or `events/`), it moves/copies the file to the target location.
3. If a thumbnail or preview was requested but missing, it creates the resized LANCZOS image on-the-fly and saves it to disk.
4. Ensures uninterrupted client experience even after server migrations or asynchronous background moves.

---

## 8. Development & Environment Setup

### Prerequisites
- Python 3.12+
- Redis Server (running on `localhost:6379`)
- OpenCV Headless (`opencv-python-headless`)

### Starting Local Services
```powershell
# 1. Activate Virtual Environment
.\env\Scripts\activate

# 2. Run Database Migrations
python manage.py migrate

# 3. Start Django Development Server
python manage.py runserver 0.0.0.0:8000

# 4. Start Celery Worker (in a separate terminal)
celery -A config worker --loglevel=info -P solo

# 5. Start Celery Beat Scheduler (in a separate terminal)
celery -A config beat --loglevel=info
```
