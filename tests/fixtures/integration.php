<?php
function double_number($number) {
    $doubled = $number * 2; // STEP_BODY
    return $doubled;
}

function evaluation_recovery() {
    $answer = 40;
    try {
        throw new RuntimeException('example'); // EVAL_EXCEPTION
    } catch (RuntimeException $error) {
        echo "caught:$answer";
    }
}

switch ($argv[1]) {
    case 'stepping':
        $input = 3;
        $result = double_number($input); // STEP_CALL
        $after = $result; // STEP_AFTER
        echo $after;
        break;
    case 'hits':
        for ($i = 0; $i < 4; $i++) {
            $result = double_number($i); // HIT_CALL
            $after = $result;
        }
        echo $result;
        break;
    case 'output':
        $ready = true; // OUTPUT_READY
        echo "one\x00";
        echo "\xfftwo é🙂";
        break;
    case 'evaluation':
        evaluation_recovery();
        break;
    default:
        throw new InvalidArgumentException('Unknown integration scenario');
}
