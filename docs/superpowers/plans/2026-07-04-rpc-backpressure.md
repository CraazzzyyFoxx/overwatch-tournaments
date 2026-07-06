# RPC Backpressure (защита от снежной лавины) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** разорвать лавину при перегрузке RabbitMQ RPC-контура: протухшие запросы удаляет брокер (per-message TTL), воркер не обрабатывает мёртвые запросы (deadline-drop middleware) и не захлёбывается (QoS prefetch), а gateway при переполнении отвечает мгновенным 503 (per-queue bulkhead).

**Architecture:** Go-gateway (`gateway/internal/rpc`) — единственный паблишер очередей `rpc.*`; он проставляет TTL/`x-deadline-ms` из `ctx.Deadline()` и режет in-flight per queue. Python-воркеры (FastStream 0.6) получают глобальный deadline-drop middleware и QoS через единую фабрику `make_rabbit_broker`; долгоживущие job-консьюмеры изолируются на собственные AMQP-каналы. Аргументы очередей НЕ меняются — redeclare/миграций нет.

**Tech Stack:** Go 1.2x + amqp091-go + prometheus/client_golang; Python 3.13 + FastStream 0.6.7 (rabbit) + prometheus_client + loguru; тесты — `go test`, pytest (unittest.IsolatedAsyncioTestCase + TestRabbitBroker).

**Spec:** `docs/superpowers/specs/2026-07-04-rpc-backpressure-design.md`

## Global Constraints

- База: ветка `feature/rpc-backpressure` от `develop`. Выполнять в отдельном worktree (superpowers:using-git-worktrees) — в основном дереве лежит незакоммиченный WIP пользователя.
- Заголовок дедлайна: `x-deadline-ms` — абсолютный unix epoch в **миллисекундах**, int64. Одинаковая строка в Go и Python.
- Слабина на clock skew в воркере: **500 мс**.
- Gateway env: `GATEWAY_RPC_MAX_INFLIGHT`, дефолт **64**, `0` = bulkhead отключён.
- Worker env: `RPC_PREFETCH_COUNT` → поле `rpc_prefetch_count: int = 16` в `BaseServiceSettings`.
- Метрики: gateway `gateway_rpc_shed_total{queue}`; воркер `rpc_stale_dropped_total{queue}`.
- Аргументы `RabbitQueue` в `backend/shared/messaging/config.py` НЕ трогать (никаких `x-message-ttl`/`x-max-length`).
- Сообщения БЕЗ `x-deadline-ms` всегда проходят без изменений (обратная совместимость).
- Коммиты — conventional commits, без Co-Authored-By.
- Windows: команды из корня repo; go — из каталога `gateway/`, pytest — из `backend/` через `uv run`.

---

### Task 1: Go — примитив bulkhead (per-queue limiter)

**Files:**
- Create: `gateway/internal/rpc/limiter.go`
- Test: `gateway/internal/rpc/limiter_test.go`

**Interfaces:**
- Produces: `newLimiter(max int) *limiter`, `(*limiter).acquire(queue string) bool`, `(*limiter).release(queue string)`. `max <= 0` — безлимит (acquire всегда true). Потокобезопасен. Task 3 встраивает его в `Client.Call`.

- [ ] **Step 1: Написать падающий тест**

Создать `gateway/internal/rpc/limiter_test.go`:

```go
package rpc

import "testing"

func TestLimiter_CapsPerQueue(t *testing.T) {
	l := newLimiter(2)
	if !l.acquire("q1") || !l.acquire("q1") {
		t.Fatal("first two acquires must succeed")
	}
	if l.acquire("q1") {
		t.Fatal("third acquire must be rejected at cap 2")
	}
	if !l.acquire("q2") {
		t.Fatal("other queues must not be affected by q1 saturation")
	}
	l.release("q1")
	if !l.acquire("q1") {
		t.Fatal("acquire after release must succeed")
	}
}

func TestLimiter_ZeroMeansUnlimited(t *testing.T) {
	l := newLimiter(0)
	for i := 0; i < 1000; i++ {
		if !l.acquire("q") {
			t.Fatal("max=0 must never reject")
		}
	}
}

func TestLimiter_ReleaseCleansUpMap(t *testing.T) {
	l := newLimiter(3)
	l.acquire("q")
	l.release("q")
	l.mu.Lock()
	_, exists := l.n["q"]
	l.mu.Unlock()
	if exists {
		t.Fatal("fully released queue must be removed from the map (no unbounded growth)")
	}
}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd gateway && go test ./internal/rpc/ -run TestLimiter -v`
Expected: FAIL — `undefined: newLimiter`

- [ ] **Step 3: Минимальная реализация**

Создать `gateway/internal/rpc/limiter.go`:

```go
package rpc

import "sync"

// limiter is a per-queue in-flight cap (bulkhead). One saturated queue rejects
// further calls to itself without affecting other queues. max <= 0 disables
// the cap entirely.
type limiter struct {
	max int
	mu  sync.Mutex
	n   map[string]int
}

func newLimiter(max int) *limiter {
	return &limiter{max: max, n: make(map[string]int)}
}

// acquire reserves an in-flight slot for queue. It reports false when the
// queue is at capacity — the caller should shed the request immediately
// instead of adding it to the broker backlog.
func (l *limiter) acquire(queue string) bool {
	if l.max <= 0 {
		return true
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.n[queue] >= l.max {
		return false
	}
	l.n[queue]++
	return true
}

// release frees a slot previously acquired for queue.
func (l *limiter) release(queue string) {
	if l.max <= 0 {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.n[queue] <= 1 {
		delete(l.n, queue)
	} else {
		l.n[queue]--
	}
}
```

- [ ] **Step 4: Тесты зелёные**

Run: `cd gateway && go test ./internal/rpc/ -run TestLimiter -v`
Expected: PASS (3 теста)

- [ ] **Step 5: Commit**

```bash
git add gateway/internal/rpc/limiter.go gateway/internal/rpc/limiter_test.go
git commit -m "feat(gateway): add per-queue in-flight limiter for RPC bulkhead"
```

---

### Task 2: Go — TTL + `x-deadline-ms` при публикации

**Files:**
- Create: `gateway/internal/rpc/deadline.go`
- Test: `gateway/internal/rpc/deadline_test.go`

**Interfaces:**
- Produces: `buildPublishing(ctx context.Context, id, replyQueue string, body []byte) amqp.Publishing` и константа `deadlineHeader = "x-deadline-ms"`. Task 3 вызывает её из `Client.Call` вместо инлайнового `amqp.Publishing{...}`.

- [ ] **Step 1: Написать падающий тест**

Создать `gateway/internal/rpc/deadline_test.go`:

```go
package rpc

import (
	"context"
	"strconv"
	"testing"
	"time"
)

func TestBuildPublishing_WithDeadline(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	deadline, _ := ctx.Deadline()

	pub := buildPublishing(ctx, "cid", "reply-q", []byte(`{"a":1}`))

	if pub.CorrelationId != "cid" || pub.ReplyTo != "reply-q" || string(pub.Body) != `{"a":1}` {
		t.Fatalf("base fields lost: %+v", pub)
	}
	ms, err := strconv.ParseInt(pub.Expiration, 10, 64)
	if err != nil {
		t.Fatalf("expiration %q is not integer milliseconds: %v", pub.Expiration, err)
	}
	if ms <= 0 || ms > 30_000 {
		t.Fatalf("expiration %dms outside (0, 30000]", ms)
	}
	got, ok := pub.Headers[deadlineHeader].(int64)
	if !ok || got != deadline.UnixMilli() {
		t.Fatalf("%s = %v, want %d", deadlineHeader, pub.Headers[deadlineHeader], deadline.UnixMilli())
	}
}

func TestBuildPublishing_NoDeadline(t *testing.T) {
	pub := buildPublishing(context.Background(), "cid", "reply-q", nil)
	if pub.Expiration != "" {
		t.Fatalf("no-deadline publish must not set TTL, got %q", pub.Expiration)
	}
	if pub.Headers != nil {
		t.Fatalf("no-deadline publish must not set headers, got %v", pub.Headers)
	}
}

func TestBuildPublishing_ExpiredContextStillPositiveTTL(t *testing.T) {
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	pub := buildPublishing(ctx, "cid", "reply-q", nil)
	if pub.Expiration != "1" {
		t.Fatalf("already-expired deadline must clamp TTL to 1ms (broker drops ASAP), got %q", pub.Expiration)
	}
}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd gateway && go test ./internal/rpc/ -run TestBuildPublishing -v`
Expected: FAIL — `undefined: buildPublishing`

- [ ] **Step 3: Минимальная реализация**

Создать `gateway/internal/rpc/deadline.go`:

```go
package rpc

import (
	"context"
	"strconv"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// deadlineHeader carries the absolute request deadline (unix epoch, ms) to the
// worker. The FastStream deadline-drop middleware reads the same name — keep
// the two in sync (backend/shared/rpc/deadline.py).
const deadlineHeader = "x-deadline-ms"

// buildPublishing assembles the AMQP message for one RPC request. When ctx
// carries a deadline the message gets a matching per-message TTL, so RabbitMQ
// itself drops it if it is still queued after the gateway has given up, plus
// the x-deadline-ms header for the worker-side stale check (messages already
// prefetched by a consumer are past TTL's reach). All RPC messages get their
// TTL from the same formula, so FIFO order matches expiry order and RabbitMQ's
// head-of-queue expiration is exact.
func buildPublishing(ctx context.Context, id, replyQueue string, body []byte) amqp.Publishing {
	pub := amqp.Publishing{
		ContentType:   contentTypeJSON,
		CorrelationId: id,
		ReplyTo:       replyQueue,
		Body:          body,
	}
	if deadline, ok := ctx.Deadline(); ok {
		ms := time.Until(deadline).Milliseconds()
		if ms < 1 {
			ms = 1 // deadline already passed: publish with minimal TTL, broker drops it at the head
		}
		pub.Expiration = strconv.FormatInt(ms, 10)
		pub.Headers = amqp.Table{deadlineHeader: deadline.UnixMilli()}
	}
	return pub
}
```

- [ ] **Step 4: Тесты зелёные**

Run: `cd gateway && go test ./internal/rpc/ -run TestBuildPublishing -v`
Expected: PASS (3 теста)

- [ ] **Step 5: Commit**

```bash
git add gateway/internal/rpc/deadline.go gateway/internal/rpc/deadline_test.go
git commit -m "feat(gateway): stamp RPC publishes with per-message TTL and x-deadline-ms"
```

---

### Task 3: Go — интеграция limiter + TTL в `Client.Call`, `ErrOverloaded`, `IsUnavailable`

**Files:**
- Modify: `gateway/internal/rpc/rpc.go`
- Test: `gateway/internal/rpc/errors_test.go` (create)

**Interfaces:**
- Consumes: `newLimiter`/`acquire`/`release` (Task 1), `buildPublishing` (Task 2).
- Produces:
  - `var ErrOverloaded = errors.New("rpc: queue overloaded")`
  - `func IsUnavailable(err error) bool` — true для `ErrNotConnected | ErrDisconnected | ErrOverloaded`;
  - `type Option func(*Client)`; `func WithMaxInFlight(n int) Option`; `func WithShedHook(fn func(queue string)) Option`;
  - `func New(url string, log *slog.Logger, opts ...Option) *Client` — вариадик, существующие вызовы `New(url, logger)` и `Dial(url)` компилируются без правок.

**ВАЖНО:** на `develop` в `rpc.go` горутины запускаются как `go c.run()` / `go c.dispatchReplies(deliveries)` (без safego). Эти строки не трогать — ориентироваться на якоря-функции, не на номера строк.

- [ ] **Step 1: Написать падающий тест**

Создать `gateway/internal/rpc/errors_test.go`:

```go
package rpc

import (
	"errors"
	"fmt"
	"testing"
)

func TestIsUnavailable(t *testing.T) {
	cases := []struct {
		err  error
		want bool
	}{
		{ErrNotConnected, true},
		{ErrDisconnected, true},
		{ErrOverloaded, true},
		{fmt.Errorf("rpc to %q: %w", "q", ErrOverloaded), true},
		{errors.New("boom"), false},
		{nil, false},
	}
	for _, c := range cases {
		if got := IsUnavailable(c.err); got != c.want {
			t.Fatalf("IsUnavailable(%v) = %v, want %v", c.err, got, c.want)
		}
	}
}

func TestNew_OptionsApply(t *testing.T) {
	shed := []string{}
	c := New("amqp://invalid-host-never-connects:5672", nil,
		WithMaxInFlight(5),
		WithShedHook(func(q string) { shed = append(shed, q) }),
	)
	defer func() { _ = c.Close() }()
	if c.limiter == nil || c.limiter.max != 5 {
		t.Fatalf("WithMaxInFlight not applied: %+v", c.limiter)
	}
	if c.onShed == nil {
		t.Fatal("WithShedHook not applied")
	}
	c.onShed("q1")
	if len(shed) != 1 || shed[0] != "q1" {
		t.Fatalf("shed hook broken: %v", shed)
	}
}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd gateway && go test ./internal/rpc/ -run "TestIsUnavailable|TestNew_OptionsApply" -v`
Expected: FAIL — `undefined: ErrOverloaded`, `undefined: IsUnavailable`, `undefined: WithMaxInFlight`

- [ ] **Step 3: Реализация в rpc.go**

3a. Рядом с существующими `ErrNotConnected`/`ErrDisconnected` добавить:

```go
// ErrOverloaded is returned when the per-queue in-flight cap is reached. The
// caller should shed the request immediately (HTTP 503) instead of adding it
// to the broker backlog — that backlog growth is what feeds the avalanche.
var ErrOverloaded = errors.New("rpc: queue overloaded")

// IsUnavailable reports whether err should map to an immediate 503: the client
// is not connected, the connection dropped mid-call, or the request was shed
// by the per-queue in-flight cap.
func IsUnavailable(err error) bool {
	return errors.Is(err, ErrNotConnected) || errors.Is(err, ErrDisconnected) || errors.Is(err, ErrOverloaded)
}
```

3b. В struct `Client` добавить поля (после `pending map[string]chan amqp.Delivery`):

```go
	limiter *limiter
	onShed  func(queue string)
```

3c. Определить опции и расширить `New` (сигнатура становится вариадиком; тело дополняется двумя строками):

```go
// Option configures a Client at construction time.
type Option func(*Client)

// WithMaxInFlight caps concurrent in-flight calls per queue (bulkhead).
// n <= 0 disables the cap.
func WithMaxInFlight(n int) Option { return func(c *Client) { c.limiter = newLimiter(n) } }

// WithShedHook registers a callback invoked with the queue name every time a
// call is rejected by the in-flight cap — used to feed metrics.
func WithShedHook(fn func(queue string)) Option { return func(c *Client) { c.onShed = fn } }

// New creates a client and starts its background connect/reconnect loop. It
// never blocks: calls made before the first connection return ErrNotConnected.
func New(url string, log *slog.Logger, opts ...Option) *Client {
	if log == nil {
		log = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	c := &Client{
		url:        url,
		log:        log,
		pending:    make(map[string]chan amqp.Delivery),
		closeCh:    make(chan struct{}),
		disconnect: make(chan struct{}),
		limiter:    newLimiter(0),
	}
	for _, opt := range opts {
		opt(c)
	}
	close(c.disconnect) // start in the disconnected state
	go c.run()
	return c
}
```

(если на базовой ветке строка запуска — `safego.Go(c.run)`, оставить её как есть; меняется только конструирование `c` и цикл опций)

3d. В `Call` после проверки `if !connected || ch == nil { return nil, ErrNotConnected }` добавить bulkhead:

```go
	if !c.limiter.acquire(queue) {
		if c.onShed != nil {
			c.onShed(queue)
		}
		return nil, fmt.Errorf("rpc to %q: %w", queue, ErrOverloaded)
	}
	defer c.limiter.release(queue)
```

3e. Там же в `Call` заменить инлайновую публикацию

```go
	if err := ch.PublishWithContext(ctx, "", queue, false, false, amqp.Publishing{
		ContentType:   contentTypeJSON,
		CorrelationId: id,
		ReplyTo:       replyQ,
		Body:          body,
	}); err != nil {
```

на

```go
	if err := ch.PublishWithContext(ctx, "", queue, false, false, buildPublishing(ctx, id, replyQ, body)); err != nil {
```

- [ ] **Step 4: Тесты и сборка зелёные**

Run: `cd gateway && go test ./internal/rpc/ -v && go build ./... && go vet ./...`
Expected: PASS все тесты пакета (limiter, deadline, errors; интероп-тесты скипаются без `GATEWAY_RPC_SPIKE`); build/vet без ошибок.

- [ ] **Step 5: Commit**

```bash
git add gateway/internal/rpc/rpc.go gateway/internal/rpc/errors_test.go
git commit -m "feat(gateway): bulkhead + deadline stamping in rpc client Call"
```

---

### Task 4: Go — мапинг `ErrOverloaded` → 503 + Retry-After на всех call-site'ах

**Files:**
- Modify: `gateway/internal/edge/dispatch.go` (func `call`)
- Modify: `gateway/internal/app/binary.go` (func `invoke`)
- Modify: `gateway/internal/balancer/binary.go` (аналогичный error-мапинг возле `b.rpc.Call`)
- Modify: `gateway/internal/parser/binary.go` (аналогичный error-мапинг возле `b.rpc.Call`)
- Modify: `gateway/internal/identity/binary.go` (func `relayAvatar`)
- Modify: `gateway/internal/identity/handler.go` (func `callIdentity`)
- Test: `gateway/internal/edge/dispatch_test.go` (append)

**Interfaces:**
- Consumes: `rpc.IsUnavailable(err)`, `rpc.ErrOverloaded` (Task 3).
- Produces: HTTP-контракт — при недоступности/перегрузке RPC любой JSON/binary эндпоинт отвечает `503 {"detail": "..."}` с заголовком `Retry-After: 1`.

- [ ] **Step 1: Написать падающий тест**

В конец `gateway/internal/edge/dispatch_test.go` добавить (в файле уже есть импорты `net/http`, `rpc` и хелперы `mockCaller`/`newTestDispatcher`/`serve`; добавить импорт `fmt` в блок import):

```go
func TestDispatch_Overloaded_503WithRetryAfter(t *testing.T) {
	m := &mockCaller{err: fmt.Errorf("rpc to %q: %w", "q", rpc.ErrOverloaded)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d, want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("Retry-After=%q, want \"1\"", got)
	}
}

func TestDispatch_Unavailable_HasRetryAfter(t *testing.T) {
	m := &mockCaller{err: rpc.ErrNotConnected}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d, want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("Retry-After=%q, want \"1\"", got)
	}
}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd gateway && go test ./internal/edge/ -run "TestDispatch_Overloaded|TestDispatch_Unavailable" -v`
Expected: FAIL — Overloaded сейчас мапится в 504 (нет ветки), Retry-After пуст.

- [ ] **Step 3: Правка error-мапинга (шаблон одинаковый во всех 6 файлах)**

В каждом файле найти блок вида:

```go
	if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
		<log>.Error("<...> unavailable", "<key>", queue, "err", err)
		writeDetail(w, http.StatusServiceUnavailable, "<...> unavailable")
		return <...>
	}
```

и заменить условие + добавить Retry-After (лог-сообщение и текст detail каждого файла сохранить как есть):

```go
	if rpc.IsUnavailable(err) {
		<log>.Error("<...> unavailable", "<key>", queue, "err", err)
		w.Header().Set("Retry-After", "1")
		writeDetail(w, http.StatusServiceUnavailable, "<...> unavailable")
		return <...>
	}
```

Конкретно:
- `gateway/internal/edge/dispatch.go` — func `call`, сообщение `"rpc unavailable"`, detail `"service unavailable"`.
- `gateway/internal/app/binary.go` — func `invoke`, `"rpc unavailable"` / `"service unavailable"`, `return nil, false`.
- `gateway/internal/balancer/binary.go` — тот же блок (после `b.rpc.Call`).
- `gateway/internal/parser/binary.go` — тот же блок (после `b.rpc.Call`).
- `gateway/internal/identity/binary.go` — func `relayAvatar`, `"identity rpc unavailable"` / `"identity service unavailable"`.
- `gateway/internal/identity/handler.go` — func `callIdentity`, `"identity rpc unavailable"` / `"identity service unavailable"`.

`gateway/internal/principal/resolver.go` НЕ трогать: там `Call` с `err == nil`-веткой и локальным фолбэком валидации — bulkhead просто ускоряет фолбэк.

Если после правки в файле не остаётся других использований `errors.Is` — убрать неиспользуемый импорт `errors` (go vet подскажет).

- [ ] **Step 4: Тесты и сборка зелёные**

Run: `cd gateway && go test ./internal/... && go vet ./...`
Expected: PASS, включая оба новых теста.

- [ ] **Step 5: Commit**

```bash
git add gateway/internal/edge/dispatch.go gateway/internal/edge/dispatch_test.go gateway/internal/app/binary.go gateway/internal/balancer/binary.go gateway/internal/parser/binary.go gateway/internal/identity/binary.go gateway/internal/identity/handler.go
git commit -m "feat(gateway): map bulkhead overload to fast 503 with Retry-After on all rpc call sites"
```

---

### Task 5: Go — конфиг, метрика shed, wiring в main

**Files:**
- Modify: `gateway/internal/config/config.go`
- Modify: `gateway/internal/metrics/metrics.go`
- Modify: `gateway/cmd/gateway/main.go`
- Modify: `backend/env/gateway.env.example`
- Test: `gateway/internal/metrics/metrics_test.go` (append)

**Interfaces:**
- Consumes: `rpc.WithMaxInFlight`, `rpc.WithShedHook` (Task 3).
- Produces: `Config.RPCMaxInFlight int` (env `GATEWAY_RPC_MAX_INFLIGHT`, дефолт 64); `(*metrics.Metrics).RPCShed(queue string)` — инкремент counter `gateway_rpc_shed_total{queue}`.

- [ ] **Step 1: Написать падающий тест метрики**

В конец `gateway/internal/metrics/metrics_test.go` добавить (импорты `net/http/httptest`, `strings` уже используются в файле — проверить и дополнить блок import при необходимости):

```go
func TestRPCShedCounter(t *testing.T) {
	m := New()
	m.RPCShed("rpc.app.users.list")
	m.RPCShed("rpc.app.users.list")

	req := httptest.NewRequest("GET", "/metrics", nil)
	rec := httptest.NewRecorder()
	m.Handler().ServeHTTP(rec, req)

	body := rec.Body.String()
	want := `gateway_rpc_shed_total{queue="rpc.app.users.list"} 2`
	if !strings.Contains(body, want) {
		t.Fatalf("metrics output missing %q", want)
	}
}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd gateway && go test ./internal/metrics/ -run TestRPCShedCounter -v`
Expected: FAIL — `m.RPCShed undefined`

- [ ] **Step 3: Реализация**

3a. `gateway/internal/metrics/metrics.go` — в struct `Metrics` добавить поле:

```go
	rpcShed     *prometheus.CounterVec
```

в `New()` после инициализации `wsConns` добавить:

```go
		rpcShed: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_rpc_shed_total",
			Help: "RPC requests rejected by the per-queue in-flight cap (bulkhead), by queue.",
		}, []string{"queue"}),
```

и дополнить регистрацию: `reg.MustRegister(m.requests, m.duration, m.activeUsers, m.wsConns, m.rpcShed)`.

Метод (рядом с `Handler`):

```go
// RPCShed records one RPC request rejected by the per-queue in-flight cap.
func (m *Metrics) RPCShed(queue string) { m.rpcShed.WithLabelValues(queue).Inc() }
```

3b. `gateway/internal/config/config.go` — в struct `Config` после `AuthRateWindow time.Duration` добавить:

```go
	// RPCMaxInFlight caps concurrent in-flight RPC calls per queue (bulkhead).
	// When a queue is saturated the gateway sheds the request with an immediate
	// 503 instead of queueing it for up to the full RPC timeout. 0 disables.
	RPCMaxInFlight int
```

в `Load()` рядом с `AuthRateWindow`:

```go
		RPCMaxInFlight:   getenvInt("GATEWAY_RPC_MAX_INFLIGHT", 64),
```

3c. `gateway/cmd/gateway/main.go` — перенести создание метрик ВЫШЕ rpc-клиента и передать опции. Было (два места):

```go
	// RPC client for calling identity-svc (and future headless domain services)
	// over RabbitMQ request-reply. Non-blocking: reconnects in the background.
	rpcClient := rpc.New(cfg.RabbitMQURL, logger)
```

и ниже:

```go
	// Usage metrics (Prometheus): per-route request stats + active users. The
	// recorder buffers active-user IDs and flushes them to Redis (HyperLogLog).
	mtr := metrics.New()
	activeUsers := metrics.NewRecorder(rdb, logger)
```

Стало (метрики создаются первыми, затем клиент с bulkhead-опциями; комментарии сохранить):

```go
	// Usage metrics (Prometheus): per-route request stats + active users. The
	// recorder buffers active-user IDs and flushes them to Redis (HyperLogLog).
	// Created before the RPC client so the bulkhead can report shed requests.
	mtr := metrics.New()
	activeUsers := metrics.NewRecorder(rdb, logger)

	// RPC client for calling identity-svc (and future headless domain services)
	// over RabbitMQ request-reply. Non-blocking: reconnects in the background.
	// Per-queue in-flight cap sheds overload with an immediate 503 (see
	// GATEWAY_RPC_MAX_INFLIGHT); every publish carries a TTL + x-deadline-ms.
	rpcClient := rpc.New(cfg.RabbitMQURL, logger,
		rpc.WithMaxInFlight(cfg.RPCMaxInFlight),
		rpc.WithShedHook(mtr.RPCShed),
	)
```

(строки `mtr := metrics.New()` и `activeUsers := ...` на старом месте удалить).

3d. `backend/env/gateway.env.example` — добавить в конец:

```
# RPC bulkhead: max concurrent in-flight RPC calls per queue. Above the cap the
# gateway sheds requests with an immediate 503 instead of queueing them. 0 = off.
GATEWAY_RPC_MAX_INFLIGHT=64
```

- [ ] **Step 4: Тесты и сборка зелёные**

Run: `cd gateway && go test ./... && go build ./... && go vet ./...`
Expected: PASS (все пакеты), build/vet чисто.

- [ ] **Step 5: Commit**

```bash
git add gateway/internal/metrics/metrics.go gateway/internal/metrics/metrics_test.go gateway/internal/config/config.go gateway/cmd/gateway/main.go backend/env/gateway.env.example
git commit -m "feat(gateway): GATEWAY_RPC_MAX_INFLIGHT config + gateway_rpc_shed_total metric + wiring"
```

---

### Task 6: Python — deadline-drop middleware

**Files:**
- Create: `backend/shared/rpc/deadline.py`
- Test: `backend/tests/test_rpc_deadline.py`

**Interfaces:**
- Produces: `DEADLINE_HEADER = "x-deadline-ms"`, `DEADLINE_SLACK_MS = 500`, класс `DeadlineDropMiddleware(BaseMiddleware)`, counter `RPC_STALE_DROPPED_TOTAL` (`rpc_stale_dropped_total{queue}`). Task 7 передаёт класс в `RabbitBroker(middlewares=...)`.
- Семантика: сообщение с `x-deadline-ms` в прошлом (минус слабина 500 мс) — `await msg.ack()`, WARNING-лог, инкремент метрики, хендлер НЕ вызывается, возврат `None`. Без заголовка / с нечитаемым значением / свежее — `await call_next(msg)` без изменений.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_rpc_deadline.py`:

```python
"""Tests for the shared RPC deadline-drop middleware."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from faststream.rabbit import RabbitBroker, TestRabbitBroker  # noqa: E402

from shared.rpc.deadline import (  # noqa: E402
    DEADLINE_HEADER,
    RPC_STALE_DROPPED_TOTAL,
    DeadlineDropMiddleware,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


class DeadlineDropTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.broker = RabbitBroker(middlewares=(DeadlineDropMiddleware,))
        self.calls: list[dict] = []

        @self.broker.subscriber("rpc.test.echo")
        async def handler(data: dict) -> dict:
            self.calls.append(data)
            return {"ok": True}

    async def test_expired_message_dropped_without_calling_handler(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 1}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() - 10_000})
        assert self.calls == []

    async def test_fresh_message_processed(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 1}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() + 60_000})
        assert self.calls == [{"x": 1}]

    async def test_message_without_header_processed(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 2}, "rpc.test.echo")
        assert self.calls == [{"x": 2}]

    async def test_unparseable_header_processed(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 5}, "rpc.test.echo", headers={DEADLINE_HEADER: "not-a-number"})
        assert self.calls == [{"x": 5}]

    async def test_slack_keeps_barely_late_message_alive(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 3}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() - 100})
        assert self.calls == [{"x": 3}]

    async def test_drop_increments_stale_counter(self) -> None:
        before = RPC_STALE_DROPPED_TOTAL.labels(queue="rpc.test.echo")._value.get()
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 4}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() - 10_000})
        after = RPC_STALE_DROPPED_TOTAL.labels(queue="rpc.test.echo")._value.get()
        assert after == before + 1
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_rpc_deadline.py -v`
Expected: FAIL на импорте — `ModuleNotFoundError: No module named 'shared.rpc.deadline'`

- [ ] **Step 3: Минимальная реализация**

Создать `backend/shared/rpc/deadline.py`:

```python
"""Deadline-drop middleware: skip RPC requests whose gateway client already gave up.

The Go gateway stamps every RPC publish with an ``x-deadline-ms`` header (unix
epoch ms of its context deadline) and a matching per-message TTL. The TTL lets
RabbitMQ drop stale messages that are still *queued*; this middleware covers
the rest — messages already prefetched by the consumer when they expired. The
handler never runs for such messages: the gateway discarded its correlation
waiter at timeout, so any reply would be thrown away, and processing the
request only burns DB/CPU during overload and feeds the avalanche.

Messages without the header (background events, jobs) pass through untouched,
so the middleware is safe to install broker-wide via ``make_rabbit_broker``.
"""

from __future__ import annotations

import time
from typing import Any

from faststream.middlewares import BaseMiddleware
from loguru import logger
from prometheus_client import Counter

__all__ = ("DEADLINE_HEADER", "DEADLINE_SLACK_MS", "RPC_STALE_DROPPED_TOTAL", "DeadlineDropMiddleware")

# Keep in sync with the Go gateway (gateway/internal/rpc/deadline.go).
DEADLINE_HEADER = "x-deadline-ms"
# Absorbs gateway<->worker clock skew (containers share the host clock) so a
# still-live request is never dropped by a marginally fast worker clock.
DEADLINE_SLACK_MS = 500

RPC_STALE_DROPPED_TOTAL = Counter(
    "rpc_stale_dropped_total",
    "RPC requests dropped unprocessed because their gateway deadline had already passed.",
    ("queue",),
)


def _deadline_ms(headers: dict[str, Any] | None) -> int | None:
    raw = (headers or {}).get(DEADLINE_HEADER)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class DeadlineDropMiddleware(BaseMiddleware):
    """Ack-and-skip messages whose ``x-deadline-ms`` already passed."""

    async def consume_scope(self, call_next: Any, msg: Any) -> Any:
        deadline = _deadline_ms(getattr(msg, "headers", None))
        if deadline is not None:
            now_ms = time.time() * 1000
            if now_ms > deadline + DEADLINE_SLACK_MS:
                queue = getattr(getattr(msg, "raw_message", None), "routing_key", None) or "unknown"
                RPC_STALE_DROPPED_TOTAL.labels(queue=queue).inc()
                logger.bind(queue=queue, overdue_ms=round(now_ms - deadline)).warning(
                    "Dropping stale RPC request: gateway deadline passed before processing"
                )
                # Ack explicitly: the short-circuit skips the subscriber's own
                # acknowledgement path. StreamMessage tracks committed state, so
                # a downstream double-ack is a no-op.
                await msg.ack()
                return None
        return await call_next(msg)
```

- [ ] **Step 4: Тесты зелёные**

Run: `cd backend && uv run pytest tests/test_rpc_deadline.py -v`
Expected: PASS (6 тестов).

Если `test_expired_message_dropped_without_calling_handler` падает из-за того, что FastStream пытается опубликовать reply на короткое замыкание и это ломает TestRabbitBroker — допустимая альтернатива: вместо `return None` поднимать `faststream.exceptions.AckMessage` ПОСЛЕ инкремента метрики и лога (и убрать явный `await msg.ack()` — AckMessage делает ack сам). Тесты менять НЕ нужно — они проверяют только «хендлер не вызван + ack».

- [ ] **Step 5: Commit**

```bash
git add backend/shared/rpc/deadline.py backend/tests/test_rpc_deadline.py
git commit -m "feat(shared): deadline-drop middleware skips RPC requests past their gateway deadline"
```

---

### Task 7: Python — prefetch + middleware в `make_rabbit_broker`, настройка в BaseServiceSettings

**Files:**
- Modify: `backend/shared/observability/broker.py`
- Modify: `backend/shared/core/config.py` (class `BaseServiceSettings`)
- Modify: `backend/env/common.env.example`
- Test: `backend/tests/test_rabbit_broker_factory.py` (create)

**Interfaces:**
- Consumes: `DeadlineDropMiddleware` (Task 6).
- Produces: `make_rabbit_broker(url, *, logger, log_level=logging.DEBUG, prefetch_count: int | None = None, **kwargs)` — всегда ставит `DeadlineDropMiddleware` первым в `middlewares`; при `prefetch_count` передаёт `default_channel=Channel(prefetch_count=N)`. Поле `BaseServiceSettings.rpc_prefetch_count: int = 16` (env `RPC_PREFETCH_COUNT`). Task 8 прокидывает его в энтрипойнтах.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_rabbit_broker_factory.py`:

```python
"""Tests for the shared RabbitBroker factory policy (deadline middleware + QoS)."""

from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

import pytest  # noqa: E402
from loguru import logger  # noqa: E402

from shared.observability import make_rabbit_broker  # noqa: E402
from shared.rpc.deadline import DeadlineDropMiddleware  # noqa: E402


def test_deadline_middleware_always_installed() -> None:
    broker = make_rabbit_broker("amqp://guest:guest@localhost:5672", logger=logger)
    assert DeadlineDropMiddleware in list(broker.config.broker_middlewares)


def test_extra_middlewares_are_kept() -> None:
    class Extra:  # noqa: B903 - sentinel only
        pass

    broker = make_rabbit_broker(
        "amqp://guest:guest@localhost:5672", logger=logger, middlewares=(Extra,)
    )
    mws = list(broker.config.broker_middlewares)
    assert DeadlineDropMiddleware in mws
    assert Extra in mws


def test_prefetch_passes_default_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeBroker:
        def __init__(self, url: str, **kwargs: object) -> None:
            captured["url"] = url
            captured.update(kwargs)

    import shared.observability.broker as broker_mod

    monkeypatch.setattr(broker_mod, "RabbitBroker", FakeBroker)
    broker_mod.make_rabbit_broker("amqp://x", logger=logger, prefetch_count=16)
    assert captured["default_channel"].prefetch_count == 16


def test_no_prefetch_means_no_default_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeBroker:
        def __init__(self, url: str, **kwargs: object) -> None:
            captured.update(kwargs)

    import shared.observability.broker as broker_mod

    monkeypatch.setattr(broker_mod, "RabbitBroker", FakeBroker)
    broker_mod.make_rabbit_broker("amqp://x", logger=logger)
    assert "default_channel" not in captured


def test_base_settings_expose_rpc_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared.core.config import BaseServiceSettings

    class S(BaseServiceSettings):
        postgres_user: str = "u"
        postgres_password: str = "p"
        postgres_db: str = "d"
        postgres_host: str = "h"
        postgres_port: str = "5432"

    assert S().rpc_prefetch_count == 16
    monkeypatch.setenv("RPC_PREFETCH_COUNT", "5")
    assert S().rpc_prefetch_count == 5
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_rabbit_broker_factory.py -v`
Expected: FAIL — `make_rabbit_broker() got an unexpected keyword argument 'prefetch_count'` / middleware отсутствует / у Settings нет `rpc_prefetch_count`.

- [ ] **Step 3: Реализация**

3a. Переписать `backend/shared/observability/broker.py`:

```python
"""Shared RabbitBroker factory.

Centralizes the FastStream broker construction policy so every service inherits
the same logging verbosity, the deadline-drop middleware, and (opt-in) consumer
QoS. Mirrors the ``setup_*`` helpers in this package.
"""

import logging
from typing import Any

from faststream.rabbit import Channel, RabbitBroker

from shared.rpc.deadline import DeadlineDropMiddleware


def make_rabbit_broker(
    url: str,
    *,
    logger: Any,
    log_level: int = logging.DEBUG,
    prefetch_count: int | None = None,
    **kwargs: Any,
) -> RabbitBroker:
    """Create a RabbitBroker with the shared consumption policy.

    - FastStream's per-message access logs are demoted to ``log_level``
      (default DEBUG) so they stay below the normal INFO sink but reappear
      under ``LOG_LEVEL=debug``. Consume failures still log at ERROR.
    - ``DeadlineDropMiddleware`` is always installed: RPC requests whose
      gateway deadline already passed are acked and skipped. Messages without
      the ``x-deadline-ms`` header (background events/jobs) are unaffected.
    - ``prefetch_count`` (optional) sets the default-channel QoS: it bounds
      concurrent message processing per process, keeping the backlog in the
      queue — where the gateway's per-message TTL can expire it — instead of
      the consumer buffer. RPC-hosting entrypoints pass
      ``settings.rpc_prefetch_count`` (env ``RPC_PREFETCH_COUNT``).

    Args:
        url: AMQP connection URL.
        logger: Logger passed to the broker (the service's loguru logger).
        log_level: Level for FastStream's per-message access logs.
        prefetch_count: Default-channel QoS cap; ``None`` keeps the broker
            default (unlimited).
        **kwargs: Forwarded verbatim to ``RabbitBroker``; ``middlewares`` is
            merged after the deadline middleware.

    Returns:
        A configured ``RabbitBroker``.
    """
    middlewares = (DeadlineDropMiddleware, *kwargs.pop("middlewares", ()))
    if prefetch_count:
        kwargs.setdefault("default_channel", Channel(prefetch_count=prefetch_count))
    return RabbitBroker(url, logger=logger, log_level=log_level, middlewares=middlewares, **kwargs)
```

3b. `backend/shared/core/config.py` — в class `BaseServiceSettings` (рядом с блоком `# Database pool`) добавить:

```python
    # RabbitMQ consumer QoS: max unacked messages per default channel. Bounds
    # per-process concurrency so overload backlog stays in the queue (where the
    # gateway's per-message TTL can drop stale requests) instead of the
    # consumer buffer. Env: RPC_PREFETCH_COUNT.
    rpc_prefetch_count: int = 16
```

3c. `backend/env/common.env.example` — добавить:

```
# RabbitMQ consumer QoS for workers: max unacked messages per channel.
RPC_PREFETCH_COUNT=16
```

- [ ] **Step 4: Тесты зелёные**

Run: `cd backend && uv run pytest tests/test_rabbit_broker_factory.py tests/test_rpc_deadline.py -v`
Expected: PASS (11 тестов суммарно).

- [ ] **Step 5: Commit**

```bash
git add backend/shared/observability/broker.py backend/shared/core/config.py backend/env/common.env.example backend/tests/test_rabbit_broker_factory.py
git commit -m "feat(shared): rabbit broker factory installs deadline middleware + optional QoS prefetch"
```

---

### Task 8: Python — прокинуть prefetch в энтрипойнты + изолировать job-каналы

**Files:**
- Modify: `backend/app-service/serve.py`
- Modify: `backend/app-service/src/services/tournament_events.py`
- Modify: `backend/tournament-service/serve.py`
- Modify: `backend/tournament-service/src/services/tournament/recalculation_events.py`
- Modify: `backend/parser-service/serve.py`
- Modify: `backend/balancer-service/serve.py`
- Modify: `backend/analytics-service/serve_rpc.py`
- Modify: `backend/identity-service/serve.py`

**Interfaces:**
- Consumes: `make_rabbit_broker(..., prefetch_count=...)` и `BaseServiceSettings.rpc_prefetch_count` (Task 7); `faststream.rabbit.Channel` (per-subscriber канал).
- Produces: поведение рантайма; новых API нет.

Правки механические — по каждому файлу:

- [ ] **Step 1: RPC-энтрипойнты передают prefetch**

В каждом файле найти строку `broker = make_rabbit_broker(...)` и добавить аргумент:

- `backend/app-service/serve.py`:
  `broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count)`
- `backend/tournament-service/serve.py`:
  `broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count)`
- `backend/parser-service/serve.py`:
  `broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count)`
- `backend/balancer-service/serve.py` (конфиг тут — объект `config` из `src.core.config`):
  `broker = make_rabbit_broker(config.rabbitmq_url, logger=logger, prefetch_count=config.rpc_prefetch_count)`
- `backend/analytics-service/serve_rpc.py`:
  `broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count)`
- `backend/identity-service/serve.py`:
  `broker = make_rabbit_broker(settings.rabbitmq_url, logger=logger, prefetch_count=settings.rpc_prefetch_count)`

`backend/analytics-service/serve.py` (тяжёлый analytics-worker: только job/train/infer, RPC в процессе нет) — НЕ трогать.
`backend/discord-service/main.py` — НЕ трогать.

- [ ] **Step 2: Выделенные каналы для долгоживущих консьюмеров**

Долгие джобы не должны занимать QoS-слоты RPC-канала (и наоборот), поэтому job-сабскрайберы, живущие в одном процессе с RPC, получают собственный `Channel`. В каждом файле добавить импорт `from faststream.rabbit import Channel` (или дополнить существующий импорт из `faststream.rabbit`) и модульную константу, затем дописать `channel=...` в декораторы:

- `backend/tournament-service/serve.py` — константа после создания брокера:

```python
# Long-running compute jobs get their own AMQP channel so a burst of bracket /
# standings recomputes can't occupy the RPC default-channel QoS slots.
_JOBS_CHANNEL = Channel(prefetch_count=4)
```

  и в оба декоратора:
  `@broker.subscriber(TOURNAMENT_BRACKET_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE, channel=_JOBS_CHANNEL)`
  `@broker.subscriber(TOURNAMENT_STANDINGS_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE, channel=_JOBS_CHANNEL)`

- `backend/tournament-service/src/services/tournament/recalculation_events.py` — модульная константа рядом с `task_router`:

```python
# Isolated channel: recalculation fan-in must not compete with RPC QoS slots.
_EVENTS_CHANNEL = Channel(prefetch_count=4)
```

  и декоратор:
  `@task_router.subscriber(TOURNAMENT_CHANGED_TOURNAMENT_QUEUE, exchange=TOURNAMENT_CHANGED_EXCHANGE, channel=_EVENTS_CHANNEL)`

- `backend/parser-service/serve.py` — константы после создания брокера:

```python
# Match-log processing is minutes-long; keep it off the RPC channel QoS.
_JOBS_CHANNEL = Channel(prefetch_count=2)
# OverFast-protective prefetch (existing setting, previously unwired).
_RANK_FETCH_CHANNEL = Channel(prefetch_count=config.settings.rank_fetch_worker_prefetch)
```

  и декораторы:
  `@broker.subscriber(UPLOAD_MATCH_LOG_QUEUE, channel=_JOBS_CHANNEL)`
  `@broker.subscriber(PROCESS_MATCH_LOG_QUEUE, channel=_JOBS_CHANNEL)`
  `@broker.subscriber(PROCESS_TOURNAMENT_LOGS_QUEUE, channel=_JOBS_CHANNEL)`
  `@broker.subscriber(ACHIEVEMENT_EVALUATE_QUEUE, channel=_JOBS_CHANNEL)`
  `@broker.subscriber(RANK_FETCH_QUEUE, channel=_RANK_FETCH_CHANNEL)`
  `@broker.subscriber(RANK_FETCH_PRIORITY_QUEUE, channel=_RANK_FETCH_CHANNEL)`

- `backend/balancer-service/serve.py` — константа после создания брокера:

```python
# Balance jobs run for minutes (MOO solver); isolate them from the RPC channel.
_JOBS_CHANNEL = Channel(prefetch_count=2)
```

  и декоратор:
  `@broker.subscriber(BALANCER_JOBS_QUEUE, decoder=_decode_balancer_message, channel=_JOBS_CHANNEL)`

- `backend/app-service/src/services/tournament_events.py` — модульная константа над `register`:

```python
# Isolated channel: cache-invalidation bursts must not compete with RPC QoS.
_EVENTS_CHANNEL = Channel(prefetch_count=4)
```

  и декоратор внутри `register`:
  `@broker.subscriber(TOURNAMENT_CHANGED_APP_QUEUE, exchange=TOURNAMENT_CHANGED_EXCHANGE, channel=_EVENTS_CHANNEL)`

- [ ] **Step 3: Синтаксис-смоук всех затронутых энтрипойнтов**

Компиляция байткода ловит синтаксические ошибки уровня модуля (полный импорт serve-модулей требует env-переменных БД — он выполняется на живом стенде в Task 9):

```bash
cd backend
uv run python -m compileall -q app-service/serve.py tournament-service/serve.py parser-service/serve.py balancer-service/serve.py analytics-service/serve_rpc.py identity-service/serve.py app-service/src/services/tournament_events.py tournament-service/src/services/tournament/recalculation_events.py
```

Expected: exit 0, вывода нет.

- [ ] **Step 4: Общий прогон shared-тестов**

Run: `cd backend && uv run pytest tests/ -q`
Expected: PASS (все тесты каталога `backend/tests`, включая новые из Task 6–7).

- [ ] **Step 5: Commit**

```bash
git add backend/app-service/serve.py backend/app-service/src/services/tournament_events.py backend/tournament-service/serve.py backend/tournament-service/src/services/tournament/recalculation_events.py backend/parser-service/serve.py backend/balancer-service/serve.py backend/analytics-service/serve_rpc.py backend/identity-service/serve.py
git commit -m "feat(backend): QoS prefetch on RPC workers + dedicated channels for long-running consumers"
```

---

### Task 9: Финальная верификация

**Files:** нет новых; только запуск проверок.

- [ ] **Step 1: Go — полный прогон**

Run: `cd gateway && go build ./... && go vet ./... && go test ./...`
Expected: build/vet чисто, все тесты PASS (интеграционные rpc-тесты скипаются без `GATEWAY_RPC_SPIKE`).

- [ ] **Step 2: Python — полный прогон shared-тестов + линт**

Run:
```bash
cd backend
uv run pytest tests/ -q
uv run ruff check shared/rpc/deadline.py shared/observability/broker.py shared/core/config.py tests/test_rpc_deadline.py tests/test_rabbit_broker_factory.py
```
Expected: pytest PASS; ruff — 0 ошибок.

- [ ] **Step 3: Пер-сервисные тесты, задетые правками serve.py**

Run (только сервисы с существующими тестами на serve-модули):
```bash
cd backend
uv run pytest parser-service/tests/test_serve_smoke.py -q
uv run pytest balancer-service/tests/ -q
```
Expected: PASS (balancer: ~200+ тестов; parser smoke зелёный).

- [ ] **Step 4: Ручная проверка сценария (если доступен dev-стенд с RabbitMQ)**

1. Поднять стенд: `docker compose up -d rabbitmq && docker compose up -d --build gateway backend tournament-worker`.
2. Убедиться в management UI (или `rabbitmqctl list_queues`) — после серии запросов `/api/v1/...` очереди `rpc.*` возвращаются к 0.
3. Отправить запрос и убедиться в headers ответа при остановленном воркере: через ~120s — 504 (как раньше), сообщение исчезает из очереди само по истечении TTL (`rabbitmqctl list_queues name messages` → 0 через ≤120s, а не навсегда).
4. Grafana/`curl localhost:9110/metrics` — присутствует `gateway_rpc_shed_total`; на воркер-метрик-порту — `rpc_stale_dropped_total`.

Expected: очереди самоочищаются, лавина не образуется.

- [ ] **Step 5: Финальный коммит (если были фиксы) и статус**

```bash
git status
git log --oneline develop..HEAD
```
Expected: рабочее дерево чистое, в ветке 8 коммитов задач (+фиксы). Ветку НЕ пушить без команды пользователя.

---

## Порядок выкатки (после мерджа, справочно)

1. Воркеры (middleware + prefetch): пересобрать/перезапустить app-svc, tournament-worker, parser, balancer-worker, analytics-svc, identity-svc.
2. Gateway (TTL + bulkhead): пересобрать/перезапустить gateway; на проде помнить про обязательный `restart nginx` после редеплоя сервиса.
3. Заголовок опционален с обеих сторон — смешанные версии безопасны в любом порядке.
4. Тюнинг под нагрузкой: `GATEWAY_RPC_MAX_INFLIGHT` (64) и `RPC_PREFETCH_COUNT` (16) — через env без пересборки.
