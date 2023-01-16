
const mineflayer = require('mineflayer');
const pathfinder = require('mineflayer-pathfinder').pathfinder
const Movements = require('mineflayer-pathfinder').Movements
const { GoalNear, GoalXZ } = require('mineflayer-pathfinder').goals
const v = require("vec3");

const host = process.env.HOST
const port = parseInt(process.env.PORT)
const username = process.env.USERNAME
const box_width = parseInt(process.env.BOX_WIDTH)
const number_steps = parseInt(process.env.NUMBER_STEPS)

const upper_limit_random_position = 1000
let initial_random_x = getRandomInt(upper_limit_random_position)
let initial_random_z = getRandomInt(upper_limit_random_position)
const box_center = v(5, -60, 2);

function getRandomInt(max) {
    return Math.floor(Math.random() * max);
}

function nextGoal(bot) {
    let x = box_center.x + getRandomInt(box_width) - (box_width / 2);
    let z = box_center.z + getRandomInt(box_width) - (box_width / 2);
    console.log(`${username} should go to ${x} and ${z}`)
    //console.log(`bot ${bot.username} should walk from ${bot.entity.position} to ${v(x, bot.entity.position.y, z)}`)
    return new GoalXZ(x, z);
}

function sleep(ms) {
    return new Promise((resolve) => {
        setTimeout(resolve, ms);
    });
}

console.log(`Creating bot with name ${username} connecting to ${host}:${port}`)
let worker_bot = mineflayer.createBot({
    host: host, // minecraft server ip
    username: username, // minecraft username
    port: port,                // only set if you need a port that isn't 25565
});
worker_bot.on('kicked', console.log)
worker_bot.on('error', console.log)
worker_bot.loadPlugin(pathfinder)



worker_bot.once("spawn", async () => {
    box_center.x = worker_bot.entity.position.x
    box_center.z = worker_bot.entity.position.z
    let defaultMove = new Movements(worker_bot)
    defaultMove.allowSprinting = false
    defaultMove.canDig = false
    worker_bot.pathfinder.setMovements(defaultMove)
    // worker_bot.pathfinder.thinkTimeout = 60000 // max 60 seconds to find path from start to finish
    let step = 0
    while (step < number_steps) {
        console.log(step)
        let goal = nextGoal(worker_bot);
        try {
            await worker_bot.pathfinder.goto(goal)
        } catch (e) {
            // if the bot cannot find a path, carry on and let it try to move somewhere else
            if (e.name != "NoPath" && e.name != "Timeout") {
                console.log(`${username} died :-(`)
                throw e
            }
        }
        step += 1
    }
    worker_bot.chat(`${username} is done!`)
    worker_bot.quit(`${username} is done!`)

    process.exit(0)
});
// parentPort.postMessage({});