# My Own Explanations (not code, just my understanding)

## database.py
contains the engine that actually forms the live connection to the database file that is society.db
also creates sessions for everytime that we make any changes to the db
Base is a special class whoever inherits it becomes a database table
get_db is a function that is needed and called before running a route
that needs a database (route means a url or  page)
it acts like a dependancy, it hands the session to the route, once route is done , automatically closes the session
so every web request gets its own session and closes it automatically as well.
## models.py
contains the tables flat bill and user.
also contains the columns it has. 

## seed.py
this basically adds starter data to the db so we have something real
to test with.
run_seed is the function that does the actual work:
creates a staff user and then adds it to the db.
data of 3 flats also added.
loop through the dictioanry where we have the 3 flats listed and add them to db one by one.
then since each bill is connected to a flat we need to have a bill column too.
create residents login account for each flat.
db.commit saves all permanently to db.
//all this happening inside for loop for each flat


## login route


## bills route
(write 1-2 sentences here)
