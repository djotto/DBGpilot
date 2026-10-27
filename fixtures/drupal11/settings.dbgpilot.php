<?php

// Development fixture only: keep controller/form code reachable on every visit.
$settings['container_yamls'][] = __DIR__ . '/services.dbgpilot.yml';
$settings['cache']['bins']['render'] = 'cache.backend.null';
$settings['cache']['bins']['page'] = 'cache.backend.null';
$settings['cache']['bins']['dynamic_page_cache'] = 'cache.backend.null';
$settings['trusted_host_patterns'] = [
  '^dbgpilot-drupal11\.ddev\.site$',
  '^ddev-dbgpilot-drupal11-web$',
  '^localhost$',
  '^127\.0\.0\.1$',
];
$config['system.performance']['css']['preprocess'] = FALSE;
$config['system.performance']['js']['preprocess'] = FALSE;
