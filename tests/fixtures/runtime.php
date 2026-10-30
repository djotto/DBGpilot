<?php
function calculate($subtotal, $discount) {
    $data = ["a\0b" => 1, 'é' => 2];
    $binary = "\xff\0";
    $many = range(0, 249);
    $long = str_repeat('abc', 1024);
    $bigint = PHP_INT_MAX;
    $total = $subtotal - $discount; // MATRIX_BREAK
    return $total;
}
echo json_encode(['total' => calculate(100, 10)], JSON_THROW_ON_ERROR);
