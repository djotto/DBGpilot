<?php

declare(strict_types=1);

header('Content-Type: application/json');

echo json_encode([
    'php' => PHP_VERSION,
    'xdebug' => phpversion('xdebug') ?: null,
    'xdebug_mode' => ini_get('xdebug.mode'),
    'xdebug_start_with_request' => ini_get('xdebug.start_with_request'),
    'xdebug_client_host' => ini_get('xdebug.client_host'),
    'xdebug_client_port' => (int) ini_get('xdebug.client_port'),
], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR);
