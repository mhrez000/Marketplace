# Three-platform parity (Web · Android · iOS)

Lens ships as three native clients over **one** Django REST API. The API is the
contract. When you change behaviour, change it in the API first, then propagate the
matching change to every client in the same unit of work.

## Repos
| Platform | Repo | Stack |
|----------|------|-------|
| Web + API | `mhrez000/Marketplace` (this repo) | Django + HTMX + DRF |
| Android | `mhrez000/Marketplace-Android` | Kotlin + Jetpack Compose |
| iOS | `mhrez000/Marketplace-iOS` | Swift + SwiftUI |

Local paths: `D:/Marketplace`, `D:/Marketplace-Android`, `D:/Marketplace-iOS`.

## The contract
The shared data shape is defined once and mirrored three times:

- **Source of truth:** `apps/api/serializers.py` + `apps/api/views.py` (this repo)
- **Android mirror:** `app/src/main/java/com/lens/app/data/Models.kt`
- **iOS mirror:** `Lens/Models.swift`

If you add or rename a field, update all three files together. The Android/iOS models
use the API's snake_case keys via `@SerialName` / `CodingKeys`, so the JSON stays the
single naming authority.

## Endpoints (v1)
```
POST   /api/v1/auth/register/     -> { token, user }
POST   /api/v1/auth/login/        -> { token, user }
GET    /api/v1/auth/me/           -> user (+is_creative, workspace) (token)
POST   /api/v1/devices/           -> {registered}        (token; push token+platform)
DELETE /api/v1/devices/           -> 204                 (token; unregister)
POST   /api/v1/bookings/{id}/upload/ -> gallery (+assets) (creative; multipart image)
GET    /calendar/<ical_token>.ics -> iCal feed           (public token URL, no auth)
GET    /api/v1/profile/           -> creative profile     (creative)
PUT    /api/v1/profile/           -> updated profile      (creative; headline/bio/styles/price)
GET    /api/v1/analytics/         -> revenue/funnel/trend (creative)
GET    /api/v1/creatives/         -> [creative]          (?q= &category= &location=)
GET    /api/v1/creatives/{slug}/  -> creative (+packages, reviews, styles, is_favourited)
GET    /api/v1/favourites/        -> [creative]          (token; saved creatives)
POST   /api/v1/creatives/{slug}/favourite/ -> {is_favourited}  (token; toggle)
GET    /api/v1/enquiries/         -> [enquiry]           (token)
POST   /api/v1/enquiries/         -> enquiry             (token)
GET    /api/v1/bookings/          -> [booking]           (token)
GET    /api/v1/bookings/{id}/     -> booking (+quote, +contract, +next_action) (token)
POST   /api/v1/bookings/{id}/sign/        -> booking      (token; body=name)
POST   /api/v1/bookings/{id}/pay-deposit/ -> booking      (token; 409 if date taken)
POST   /api/v1/bookings/{id}/pay-final/   -> booking      (token)
POST   /api/v1/bookings/{id}/deliver/      -> booking      (creative; body=url,title)
POST   /api/v1/bookings/{id}/advance/       -> booking      (creative; step=shoot_completed|start_editing)
POST   /api/v1/bookings/{id}/review/        -> booking      (client; rating/title/body)
POST   /api/v1/bookings/{id}/dispute/       -> booking      (participant; reason/detail)
GET    /api/v1/availability/         -> {blocked}           (creative)
POST   /api/v1/availability/block/   -> {blocked}           (creative; date)
POST   /api/v1/availability/unblock/ -> {blocked}           (creative; date)
GET    /api/v1/leads/               -> [enquiry]           (creative; their leads)
POST   /api/v1/leads/{id}/quote/    -> quote               (creative; amount, title, deposit_pct)
POST   /api/v1/quotes/{id}/accept/  -> booking            (token; creates it)
POST   /api/v1/quotes/{id}/decline/ -> {status}           (token)
GET    /api/v1/galleries/{id}/      -> gallery (+assets)   (token; client-scoped)
POST   /api/v1/assets/{id}/favourite/ -> asset (toggled)  (token)
GET    /api/v1/messages/          -> [thread summary]    (token)
GET    /api/v1/messages/{id}/     -> thread (+messages)  (token; marks read)
POST   /api/v1/messages/{id}/     -> message             (token; body=text)
```
Auth: DRF token in the `Authorization: Token <key>` header. Mobile clients persist it
(Android DataStore, iOS UserDefaults) and confirm it on launch via `/auth/me/`.

## Change checklist
For any user-facing or data change:
1. **API** — update serializer/view; add/adjust a test in `apps/api/tests.py`; run the suite.
2. **Android** — update `Models.kt` / the relevant ViewModel + screen; `./gradlew assembleDebug`.
3. **iOS** — update `Models.swift` / the relevant view model + view (build on a Mac).
4. Commit + push all three repos.

## Base URLs per build
- Android debug: `http://10.0.2.2:8000/api/v1/` (emulator → host dev server)
- iOS debug: `http://127.0.0.1:8000/api/v1/`
- Both release: `https://lens.fly.dev/api/v1/`

## Push notifications — going live
The backend is built and inert until keyed (same pattern as SMS/Stripe):
1. Set `FCM_SERVER_KEY` (Firebase Cloud Messaging). `notify()`/`dispatch()` then
   fan out to every device registered via `POST /api/v1/devices/`.
2. **Android**: add Firebase (`google-services.json` + the google-services Gradle
   plugin + `firebase-messaging`), get the FCM token, call
   `repository.registerPushToken(token)` (hook already present). The plugin needs
   the json file, so it isn't added to the repo yet.
3. **iOS**: enable Push Notifications capability + an APNs key in Firebase,
   request authorization, call `APIClient.registerDevice(token:)` (hook present).

## In-app photo galleries
Creatives can deliver either a link (Drive/Dropbox) **or** uploaded photos
(`POST /bookings/{id}/upload/`, multipart). Uploaded media is served from
`MEDIA_URL` (off the Fly volume in prod).

## Calendar sync
Each workspace has a secret `ical_token`; the creative subscribes to
`/calendar/<token>.ics` in Google/Apple Calendar (shoots, due dates, blocked
days). The subscribe URL is returned by `GET /api/v1/availability/` as `ical_url`.

## Test accounts (password `lens12345`)
`olivia@lens.test` (client) · `harper@lens.test` (creative) · `admin@lens.test` (staff).
Reseed with `python manage.py seed_demo`.
