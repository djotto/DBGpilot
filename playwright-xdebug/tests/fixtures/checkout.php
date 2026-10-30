<?php
declare(strict_types=1);
function checkout(string $code): array {
    $subtotal = 100;
    $discount = $code === 'SAVE10' ? 10 : 0;
    $binary = "\xff\0x";
    $bigint = PHP_INT_MAX;
    $spaced = "  é🙂  ";
    $big = range(0, 249);
    $nested = ['list' => [1, 2.5, 'three'], 'flag' => false, 'none' => null];
    $binaryKeys = ["bad\0\xff" => 'value'];
    if (isset($_GET['slow'])) usleep(150000);
    if (isset($_GET['exception'])) throw new RuntimeException('fixture exception');
    $total = $subtotal - $discount; // BREAKPOINT: inspect checkout
    return compact('total', 'discount');
}
try {
    $checkout = checkout((string) ($_POST['code'] ?? $_GET['code'] ?? ''));
} catch (RuntimeException $error) {
    http_response_code(500);
    echo 'Fixture exception: ' . htmlspecialchars($error->getMessage(), ENT_QUOTES, 'UTF-8');
    return;
}
if (isset($_GET['json'])) {
    header('Content-Type: application/json');
    echo json_encode($checkout, JSON_THROW_ON_ERROR);
    return;
}
?>
<!doctype html><html lang="en"><meta charset="utf-8"><title>Debugger checkout</title>
<form method="post"><label>Code <input name="code"></label><button>Apply</button></form>
<output data-testid="total"><?= $checkout['total'] ?></output>
<button id="ajax" type="button" onclick="fetch('/checkout.php?json=1&code=SAVE10').then(r=>r.json()).then(v=>document.querySelector('output').textContent=v.total)">AJAX</button>
</html>
