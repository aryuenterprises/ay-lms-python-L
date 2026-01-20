import random
money=int(input('enter the money for each 1Rs 1 chance:'))
chances=money
while chances>0:
    ai = random.randint(1, 5)
    user_input=int(input('choose any number from 1 to 5:'))
    if ai==user_input:
         print(f'you have won{money * money}RS')
    else:
        print('Try again..')
    chances-=1

