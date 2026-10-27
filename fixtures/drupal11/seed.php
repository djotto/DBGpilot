<?php

use Drupal\node\Entity\Node;
use Drupal\node\Entity\NodeType;
use Drupal\field\Entity\FieldConfig;
use Drupal\field\Entity\FieldStorageConfig;
use Drupal\user\Entity\User;

// Only the fixture-owned account/page are reseeded. Other content is retained.
$admin = User::load(1);
$admin->setUsername('admin');
$admin->setPassword('dbgpilot-admin');
$admin->setEmail('admin@example.test');
$admin->activate();
$admin->save();

$type = NodeType::load('page');
if (!$type) {
  $type = NodeType::create(['type' => 'page', 'name' => 'Basic page']);
  $type->save();
}
if (!FieldStorageConfig::loadByName('node', 'body')) {
  FieldStorageConfig::create(['field_name' => 'body', 'entity_type' => 'node', 'type' => 'text_with_summary'])->save();
}
if (!FieldConfig::loadByName('node', 'page', 'body')) {
  FieldConfig::create(['field_name' => 'body', 'entity_type' => 'node', 'bundle' => 'page', 'label' => 'Body'])->save();
}
$displays = \Drupal::service('entity_display.repository');
$displays->getFormDisplay('node', 'page')->setComponent('body', ['type' => 'text_textarea_with_summary'])->save();
$displays->getViewDisplay('node', 'page')->setComponent('body', ['type' => 'text_default', 'label' => 'hidden'])->save();

$uuid = '2c05a3bd-8ed1-4e80-b6df-5f8af2cbd001';
$existing = \Drupal::entityTypeManager()->getStorage('node')->loadByProperties(['uuid' => $uuid]);
$page = $existing ? reset($existing) : Node::create(['type' => 'page', 'uuid' => $uuid, 'uid' => 1]);
$page->setTitle('DBGpilot seeded page');
$page->set('body', ['value' => 'A seeded Drupal page for interactive debugging.', 'format' => 'plain_text']);
$page->setPublished();
$page->save();

\Drupal::configFactory()->getEditable('system.site')
  ->set('name', 'DBGpilot Drupal 11')
  ->set('page.front', '/node/' . $page->id())
  ->save();
\Drupal::state()->set('dbgpilot.fixture', TRUE);

$state = [
  'fixture' => 'dbgpilot-drupal11',
  'drupal' => \Drupal::VERSION,
  'php' => PHP_VERSION,
  'xdebug' => phpversion('xdebug'),
  'database' => \Drupal::database()->query('SELECT VERSION()')->fetchField(),
  'node_id' => (int) $page->id(),
  'node_path' => '/node/' . $page->id(),
  'node_title' => $page->label(),
  'url' => 'https://dbgpilot-drupal11.ddev.site',
  'test_url' => 'http://ddev-dbgpilot-drupal11-web',
];
file_put_contents(DRUPAL_ROOT . '/../fixture-state.json', json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");
echo json_encode(['event' => 'drupal_fixture_ready'] + $state, JSON_UNESCAPED_SLASHES) . "\n";
