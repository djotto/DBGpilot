<?php

declare(strict_types=1);

namespace Harness;

function checkout(string $code): array
{
    $subtotal = 100;
    $discount = $code === 'SAVE10' ? 10 : 0;
    $total = $subtotal - $discount; // BREAKPOINT: inspect subtotal and discount here.

    return compact('code', 'subtotal', 'discount', 'total');
}
