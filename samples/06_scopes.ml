int x = 1;
{
    int x = 2;       // shadows the outer x
    print(x);
}
print(x);
