/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');

function source(...parts) {
  const file = path.join(root, ...parts);
  assert.equal(fs.existsSync(file), true, `${file} must exist`);
  return fs.readFileSync(file, 'utf8');
}

test('notification center exposes durable in-app items and explicit destination controls', () => {
  const page = source('app', '(dashboard)', 'notifications', 'page.tsx');
  assert.match(page, /\/notifications\/inbox/);
  assert.match(page, /\/notifications\/destinations/);
  assert.match(page, /\/notifications\/subscriptions/);
  assert.match(page, /confirm_send/);
  assert.match(page, /Slack Incoming Webhook/);
  assert.match(page, /External delivery is opt-in/);
  assert.match(page, /destinationChoice === 'in_app' \? 'immediate' : frequency/);
  assert.match(page, /In-app history is always immediate/);
  assert.match(page, /useEffect/);
  assert.match(page, /matchingSubscription/);
  assert.match(page, /shared across every destination/i);
  assert.doesNotMatch(page, /secret_ciphertext/);
});

test('notification center exposes redacted delivery audit and failure status', () => {
  const page = source('app', '(dashboard)', 'notifications', 'page.tsx');
  assert.match(page, /\/notifications\/delivery-attempts/);
  assert.match(page, /Delivery audit/);
  assert.match(page, /provider_response_class/);
  assert.doesNotMatch(page, /secret_ciphertext/);
});

test('manager workbench provides a canonical user-scoped follow control', () => {
  const control = source('components', 'research', 'ManagerFollowButton.tsx');
  assert.match(control, /\/notifications\/manager-follows/);
  assert.match(control, /Following/);
  const manager = source('app', '(dashboard)', '13f', 'managers', '[id]', 'page.tsx');
  assert.match(manager, /ManagerFollowButton/);
});

test('primary navigation links notification center without exposing destinations', () => {
  const shell = source('components', 'layout', 'AppShell.tsx');
  assert.match(shell, /Notifications/);
  assert.match(shell, /\/notifications/);
  assert.doesNotMatch(shell, /webhook_url/);
});

test('admin notification operations surface is aggregate and readiness-oriented', () => {
  const page = source('app', '(dashboard)', 'admin', 'notifications', 'page.tsx');
  const shell = source('components', 'layout', 'AppShell.tsx');
  assert.match(page, /\/notifications\/admin\/operations/);
  assert.match(page, /Delivery operations/);
  assert.match(page, /oldest_pending_at/);
  assert.match(page, /configuration_readiness/);
  assert.match(shell, /Notification Ops/);
  assert.doesNotMatch(page, /destination_hint|notification_title|secret_ciphertext/);
});
