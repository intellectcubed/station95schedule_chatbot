## Starting state
### 0600 - 1800 42/54
### 1800 - 0600 42

## Dialog
```
# @Kohler
For Saturday we have a crew from 0700-1200.
And Midnight-0600

We are still in need of coverage from
0600-0700. 1200-1800 and 1800-0000

## System should call: 
### 0600 - 0700 42 No Crew
### 1200 - 1800 42 No Crew
### 1800 - 0000 42 No Crew

# @Mike B
54 had a call out for today due to illness, we will try and fill that spot

## System should call: 
### 0600 - 1800 54 No Crew

# @george
54 any luck?  42 starts at 7

# @mikeB
No luck yet

# @george
43 will stay on till 7

## System should call:
### 0600 - 0700 43 Add Crew

#@Kohler
Thanks George

#@MikeB
54 has a crew noon - 1500.  Still working on 1500 - 1800

## System should call:
### 1200 - 1500 54 Add Crew

# @George
Great job!

#@Kohler
42 now has a crew from 1800-0600

## System should call:
### 1800 - 0600 42 Add crew

# @DianeChrinko
Mike, I will take 15:00 to 18:00.
54 covered until 18:00

## System should call:
### 1500 - 1800 54 add crew

#@MikeB heart emoji

#@MikeB
Thank you!
```

## End state:
### 0600-0700 42[NoCrew] 43[All] 54[No Crew]
### 0700-1200 42[All] 54[No Crew]
### 1200-1800 42[No Crew] 54[All]
### 1800-0600 42[All]