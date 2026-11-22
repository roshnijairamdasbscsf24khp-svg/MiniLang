"""Example programs for the Samples menu and the samples/ folder."""

SAMPLES = [
    ("01 Arithmetic", """// precedence, parentheses, unary minus and int -> float conversion
int a = 10;
float price = 2.5;
int b;
b = (a + 5) * 2 - -1;
float total = a * price;
print(b);
print(total);
"""),
    ("02 Strings", """string first = "Mini";
string name = first + "Lang";
print(name);
print("tab\\there");
"""),
    ("03 If / else", """int age = 20;
if (age >= 18) {
    print("adult");
} else {
    print("minor");
}
bool ok = age > 10 && age < 30;
print(ok);
"""),
    ("04 While loop (factorial)", """int n = 6;
int fact = 1;
int i = 1;
while (i <= n) {
    fact = fact * i;
    i = i + 1;
}
print(fact);
"""),
    ("05 Fibonacci", """int a = 0;
int b = 1;
int count = 0;
while (count < 10) {
    print(a);
    int next = a + b;
    a = b;
    b = next;
    count = count + 1;
}
"""),
    ("06 Scopes", """int x = 1;
{
    int x = 2;       // shadows the outer x
    print(x);
}
print(x);
"""),
    ("07 Optimizer demo", """int a = 2 * 3 + 4;
int unused = 99;
if (true) {
    print(a * 1);
} else {
    print("never");
}
print(a + 0);
"""),
    ("08 Collatz", """int n = 27;
int steps = 0;
while (n != 1) {
    if (n % 2 == 0) {
        n = n / 2;
    } else {
        n = 3 * n + 1;
    }
    steps = steps + 1;
}
print(steps);
"""),
    ("09 Errors: lexical", """int a = 5;
int b = 9abc;
string s = "oops;
int c = a # 2;
"""),
    ("10 Errors: syntax", """int a = 5
print a;
int = 3;
int c = ;
if (a > 1 {
    print(a);
}
"""),
    ("11 Errors: semantic", """int a = 5;
int a = 6;
int b = 2.5;
string s = "x" - "y";
print(missing);
int d;
print(d);
int z = 10 / 0;
if (a) { print(1); }
"""),
    ("12 Errors: recovery demo", """int count = 5;
prnt(count);              // misspelt keyword
itn x = 3;                // misspelt type
if (count = 5) {          // '=' instead of '=='
    print(count)          // missing ;
}
count == 7;               // '==' instead of '='
int y 9;                  // missing '='
print count;              // missing brackets
;;                        // stray semicolons
"""),
    ("13 Errors: did you mean?", """int counter = 1;
print(countr);
float price = 2.5;
price = pricee * 2;
int big = price;
"""),
]
