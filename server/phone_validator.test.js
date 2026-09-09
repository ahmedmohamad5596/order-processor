const { convertArabicDigits, extractPhoneNumbers, validatePhone, processPhones } = require('./phone_validator');

console.log('=== Phone Validator Tests (Task 5) ===\n');

// Test 1: Arabic digits conversion
console.log('Test 1: Arabic digits conversion');
const ar = '٠١٠١٢٣٤٥٦٧٨٩';
const en = convertArabicDigits(ar);
console.log(`  Input: ${ar}`);
console.log(`  Output: ${en}`);
console.log(`  Pass: ${en === '010123456789' ? '✅' : '❌'}\n`);

// Test 2: Extract phone from text
console.log('Test 2: Extract phone from text');
const text1 = 'تليفون ٠١٠١٢٣٤٥٦٧٨';  // 11 Arabic digits = valid mobile
const phones1 = extractPhoneNumbers(text1);
console.log(`  Input: ${text1}`);
console.log(`  Extracted: ${JSON.stringify(phones1)}`);
console.log(`  Pass: ${phones1.length === 1 && phones1[0] === '01012345678' ? '✅' : '❌'}\n`);

// Test 3: Multiple phones
console.log('Test 3: Multiple phones');
const text2 = '01012345678 و 01198765432';
const phones2 = extractPhoneNumbers(text2);
console.log(`  Input: ${text2}`);
console.log(`  Extracted: ${JSON.stringify(phones2)}`);
console.log(`  Pass: ${phones2.length === 2 ? '✅' : '❌'}\n`);

// Test 4: Validate mobile
console.log('Test 4: Validate mobile');
const v1 = validatePhone('01012345678');
console.log(`  Phone: 01012345678`);
console.log(`  Result: ${JSON.stringify(v1)}`);
console.log(`  Pass: ${v1.valid && v1.type === 'mobile' ? '✅' : '❌'}\n`);

// Test 5: Validate landline
console.log('Test 5: Validate landline');
const v2 = validatePhone('0312345678');
console.log(`  Phone: 0312345678`);
console.log(`  Result: ${JSON.stringify(v2)}`);
console.log(`  Pass: ${v2.valid && v2.type === 'landline' ? '✅' : '❌'}\n`);

// Test 6: Invalid number
console.log('Test 6: Invalid number');
const v3 = validatePhone('12345');
console.log(`  Phone: 12345`);
console.log(`  Result: ${JSON.stringify(v3)}`);
console.log(`  Pass: ${!v3.valid ? '✅' : '❌'}\n`);

// Test 7: Process phones - valid case
console.log('Test 7: Process phones - valid case');
const p1 = processPhones(['01012345678']);
console.log(`  Input: ['01012345678']`);
console.log(`  Result: ${JSON.stringify(p1)}`);
console.log(`  Pass: ${p1.phone1 === '01012345678' && p1.notes.length === 0 ? '✅' : '❌'}\n`);

// Test 8: Process phones - two numbers
console.log('Test 8: Process phones - two numbers');
const p2 = processPhones(['01012345678', '01198765432']);
console.log(`  Input: ['01012345678', '01198765432']`);
console.log(`  Result: ${JSON.stringify(p2)}`);
console.log(`  Pass: ${p2.phone1 === '01012345678' && p2.phone2 === '01198765432' ? '✅' : '❌'}\n`);

// Test 9: Process phones - no number
console.log('Test 9: Process phones - no number');
const p3 = processPhones(null);
console.log(`  Input: null`);
console.log(`  Result: ${JSON.stringify(p3)}`);
console.log(`  Pass: ${p3.phone1 === '' && p3.notes.length > 0 ? '✅' : '❌'}\n`);

// Test 10: Process phones - Arabic digits (valid 11-digit number)
console.log('Test 10: Process phones - Arabic digits');
const p4 = processPhones(['٠١٠١٢٣٤٥٦٧٨']);  // 11 Arabic digits = valid mobile
console.log(`  Input: ['٠١٠١٢٣٤٥٦٧٨']`);
console.log(`  Result: ${JSON.stringify(p4)}`);
console.log(`  Pass: ${p4.phone1 === '01012345678' ? '✅' : '❌'}\n`);

console.log('=== All Tests Complete ===');
