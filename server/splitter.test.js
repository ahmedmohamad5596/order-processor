const { splitCustomers, splitMetadata, SEPARATORS } = require('./splitter');

// Test 1: Text with one separator between two customers
const test1 = 'customer1 order details |||||||| customer2 order details';
const result1 = splitCustomers(test1);
console.log('Test 1: One separator');
console.log('  Input:', test1);
console.log('  Output:', result1);
console.log('  Count:', result1.length, '(expected: 2)');
console.log('  Pass:', result1.length === 2 ? '✅' : '❌');
console.log();

// Test 2: Text with no separator (single customer)
const test2 = 'single customer order without any separator';
const result2 = splitCustomers(test2);
console.log('Test 2: No separator');
console.log('  Input:', test2);
console.log('  Output:', result2);
console.log('  Count:', result2.length, '(expected: 1)');
console.log('  Pass:', result2.length === 1 ? '✅' : '❌');
console.log();

// Test 3: Separator at beginning (empty first block)
const test3 = '|||||||| customer1 order';
const result3 = splitCustomers(test3);
console.log('Test 3: Leading separator');
console.log('  Input:', test3);
console.log('  Output:', result3);
console.log('  Count:', result3.length, '(expected: 1)');
console.log('  Pass:', result3.length === 1 ? '✅' : '❌');
console.log();

// Test 4: Separator at end (empty last block)
const test4 = 'customer1 order ||||||||';
const result4 = splitCustomers(test4);
console.log('Test 4: Trailing separator');
console.log('  Input:', test4);
console.log('  Output:', result4);
console.log('  Count:', result4.length, '(expected: 1)');
console.log('  Pass:', result4.length === 1 ? '✅' : '❌');
console.log();

// Test 5: Multiple separators with empty blocks
const test5 = '|||||||| customer1 |||||||| |||||||| customer2 ||||||||';
const result5 = splitCustomers(test5);
console.log('Test 5: Multiple separators with empty blocks');
console.log('  Input:', test5);
console.log('  Output:', result5);
console.log('  Count:', result5.length, '(expected: 2)');
console.log('  Pass:', result5.length === 2 ? '✅' : '❌');
console.log();

// Test 6: Empty input
const test6 = '';
const result6 = splitCustomers(test6);
console.log('Test 6: Empty input');
console.log('  Input:', JSON.stringify(test6));
console.log('  Output:', result6);
console.log('  Count:', result6.length, '(expected: 0)');
console.log('  Pass:', result6.length === 0 ? '✅' : '❌');
console.log();

// Test 7: Three customers
const test7 = 'customer1 |||||||| customer2 |||||||| customer3';
const result7 = splitCustomers(test7);
console.log('Test 7: Three customers');
console.log('  Input:', test7);
console.log('  Output:', result7);
console.log('  Count:', result7.length, '(expected: 3)');
console.log('  Pass:', result7.length === 3 ? '✅' : '❌');
console.log();

// Test metadata
console.log('=== Metadata Tests ===');
const meta1 = splitMetadata(test1);
console.log('Test 1 metadata:', meta1);
console.log('  Pass:', meta1.count === 2 && meta1.separatorsFound === 1 ? '✅' : '❌');

const meta2 = splitMetadata(test5);
console.log('Test 5 metadata:', meta2);
console.log('  Pass:', meta2.count === 2 && meta2.separatorsFound === 4 ? '✅' : '❌');
